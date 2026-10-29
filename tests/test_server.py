import base64
import json
import os
import shutil
import socket
import sys
import threading
import time
from urllib.error import HTTPError as URLHTTPError
from urllib.request import Request, urlopen

import pytest

from conftest import git, tiny_pdf
from treedit.cli import Handler, Server, _ws, main
from treedit.term import Sessions, ws_frame


@pytest.fixture
def server(tree, monkeypatch):
    monkeypatch.setattr(Handler, "ws", _ws(str(tree), "", [], False), raising=False)
    monkeypatch.setattr(Handler, "terms", None)
    monkeypatch.setattr(Handler, "window", None)
    monkeypatch.setattr(Handler, "context", {})
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def call(base, method, path, body=None, headers=None):
    h = {"X-Treedit": "1", **(headers or {})}
    data = json.dumps(body).encode() if body is not None else None
    req = Request(base + path, data=data, method=method, headers=h)
    try:
        with urlopen(req, timeout=5) as r:
            raw, ctype, status = r.read(), r.headers["Content-Type"], r.status
    except URLHTTPError as e:
        raw, ctype, status = e.read(), e.headers["Content-Type"], e.code
    return status, (json.loads(raw) if ctype.startswith("application/json") else raw.decode())


def test_page_and_vendor(server):
    status, page = call(server, "GET", "/")
    assert status == 200 and '"token"' in page and "/*TREEDIT_CONFIG*/" not in page
    assert call(server, "GET", "/vendor/xterm.js")[0] == 200
    assert call(server, "GET", "/vendor/katex/katex.min.js")[0] == 200
    assert call(server, "GET", "/vendor/katex/nope.js")[0] == 404
    with urlopen(server + "/vendor/katex/katex.min.css", timeout=5) as r:
        assert r.status == 200 and r.headers["Content-Type"].startswith("text/css")
    with urlopen(server + "/vendor/katex/fonts/KaTeX_Main-Regular.woff2", timeout=5) as r:
        assert r.status == 200 and r.headers["Content-Type"] == "font/woff2" and r.read(4) == b"wOF2"
    assert call(server, "GET", "/logo.svg")[1].startswith("<svg")
    assert call(server, "GET", "/vendor/nope.js")[0] == 404


def test_raw_plot(server, tree):
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0P\x0f\x00\x04\x85\x01\x80\x84\xa9\x8c!\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (tree / "fig.png").write_bytes(png)
    (tree / "fig.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    with urlopen(server + "/api/raw?path=fig.png", timeout=5) as r:
        assert r.status == 200 and r.headers["Content-Type"] == "image/png" and r.read() == png
        assert "sandbox" in r.headers["Content-Security-Policy"]
    status, svg = call(server, "GET", "/api/file?path=" + "fig.svg")
    assert status == 200 and svg["kind"] == "plot" and svg["content"].startswith("<svg")
    assert call(server, "GET", "/api/raw?path=README.md")[0] == 415
    assert call(server, "GET", "/api/raw?path=../x")[0] == 400


def test_tree_and_files(server, tree):
    status, t = call(server, "GET", "/api/tree")
    assert status == 200 and t["root"] == "proj" and t["feedback"] == []
    assert call(server, "GET", "/api/version")[1]["version"] == t["version"]
    f = call(server, "GET", "/api/file?path=pkg/b.py")[1]
    status, out = call(server, "PUT", "/api/file", {"path": "pkg/b.py", "content": "x = 2\n", "base_hash": f["hash"]})
    assert status == 200 and (tree / "pkg" / "b.py").read_text() == "x = 2\n"
    status, out = call(server, "PUT", "/api/file", {"path": "pkg/b.py", "content": "x", "base_hash": f["hash"]})
    assert status == 409 and out["disk"]["content"] == "x = 2\n"
    assert call(server, "GET", "/api/file?path=nope")[0] == 404
    assert call(server, "GET", "/api/file?path=../x")[0] == 400
    assert call(server, "GET", "/api/changes")[1]["root"] == str(tree)


def test_history_endpoint(server, tree):
    assert call(server, "GET", "/api/tree")[0] == 200
    p = tree / "pkg" / "b.py"
    p.write_text("x = 1\ny = 2\n")
    os.utime(p, None)
    assert call(server, "GET", "/api/tree")[0] == 200
    status, body = call(server, "GET", "/api/history")
    assert status == 200
    ev = [e for e in body["events"] if e["path"] == "pkg/b.py" and e["ranges"]]
    assert ev[-1]["ranges"] == [[2, 2, "add"]] and ev[-1]["by"] == "agent"


def test_new_many(server, tree):
    status, out = call(server, "POST", "/api/new", {"paths": ["m/a.txt", "m/b.txt", "README.md"], "kind": "file"})
    assert status == 200 and out["created"] == ["m/a.txt", "m/b.txt"] and out["skipped"] == ["README.md"]
    assert (tree / "m" / "a.txt").is_file() and (tree / "m" / "b.txt").is_file()
    assert call(server, "POST", "/api/new", {"paths": ["m"], "kind": "dir"})[1]["skipped"] == ["m"]
    assert call(server, "POST", "/api/new", {"path": "solo.txt"})[1] == {"ok": True, "git": False}


def test_mutations(server, tree):
    assert call(server, "POST", "/api/new", {"path": "d/n.txt"})[1] == {"ok": True, "git": False}
    assert call(server, "POST", "/api/new", {"path": "d2", "kind": "dir"})[0] == 200
    assert call(server, "PUT", "/api/note", {"path": "d", "note": "folder d"})[0] == 200
    assert call(server, "POST", "/api/note-move", {"from": "d", "to": "e"})[0] == 200
    assert call(server, "POST", "/api/rename", {"from": "d", "to": "e"})[0] == 200
    assert (tree / "e" / "n.txt").exists()
    status, fb = call(server, "POST", "/api/feedback", {"paths": ["e"], "text": "why?"})
    assert status == 200 and fb["id"] == 1
    assert call(server, "PUT", "/api/feedback", {"id": 1, "reply": "because", "status": "done"})[1]["status"] == "done"
    assert call(server, "POST", "/api/feedback-delete", {"id": 1})[0] == 200
    assert call(server, "PUT", "/api/draft", {"path": "e/n.txt", "base_hash": "x", "diff": "+y"})[0] == 200
    assert "e/n.txt" in call(server, "GET", "/api/tree")[1]["drafts"]
    assert call(server, "POST", "/api/draft-drop", {"path": "e/n.txt"})[0] == 200
    assert call(server, "POST", "/api/delete-check", {"paths": ["e", "e/n.txt"]})[1]["info"] == [
        {"tracked": False, "annotated": True},
        {"tracked": False, "annotated": False},
    ]
    assert call(server, "POST", "/api/delete", {"path": "e"})[0] == 200
    assert not (tree / "e").exists()
    assert call(server, "POST", "/api/log", {"msg": "page error"})[0] == 200
    assert call(server, "POST", "/api/nope", {})[0] == 404


def test_guards(server):
    req = Request(server + "/api/note", data=b"{}", method="PUT")
    with pytest.raises(URLHTTPError) as e:
        urlopen(req, timeout=5)
    assert e.value.code == 403
    assert call(server, "GET", "/api/tree", headers={"Host": "evil.example"})[0] == 403
    req = Request(server + "/api/note", data=b"{bad", method="PUT", headers={"X-Treedit": "1"})
    with pytest.raises(URLHTTPError) as e:
        urlopen(req, timeout=5)
    assert e.value.code == 400
    assert call(server, "GET", "/api/term")[0] == 404


def test_open_endpoint(server, tree, monkeypatch):
    import treedit.cli as tcli

    (tree / "fig.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    calls = []
    monkeypatch.setattr(tcli.shutil, "which", lambda name: "/usr/bin/inkscape" if name == "inkscape" else None)
    monkeypatch.setattr(tcli.subprocess, "Popen", lambda *a, **k: calls.append(a))
    status, out = call(server, "POST", "/api/open", {"path": "fig.svg", "app": "inkscape"})
    assert status == 200 and out["cmd"].startswith("inkscape ") and calls
    assert call(server, "POST", "/api/open", {"path": "README.md", "app": "inkscape"})[0] == 400
    monkeypatch.setattr(Handler, "loopback", False)
    assert call(server, "POST", "/api/open", {"path": "fig.svg", "app": "inkscape"})[0] == 403


def test_pdf_endpoints(server, tree):
    if not (shutil.which("pdfinfo") and shutil.which("pdftoppm")):
        pytest.skip("needs poppler-utils")
    tiny_pdf(tree / "doc.pdf")
    status, info = call(server, "GET", "/api/pdf/info?path=doc.pdf")
    assert status == 200 and info["pages"] == 1
    with urlopen(server + "/api/pdf?path=doc.pdf&page=1", timeout=10) as r:
        assert r.headers["Content-Type"] == "image/png"
        assert r.read().startswith(b"\x89PNG")
    with urlopen(server + "/api/raw?path=doc.pdf", timeout=10) as r:
        assert r.headers["Content-Type"] == "application/pdf"
        assert "Content-Security-Policy" not in r.headers  # the browser fallback must be able to load it
    assert call(server, "GET", "/api/pdf/info?path=README.md")[0] == 415


def test_diagram_endpoint(server):
    if not shutil.which("d2"):
        pytest.skip("needs d2")
    status, out = call(server, "POST", "/api/diagram", {"kind": "d2", "source": "a -> b\n"})
    assert status == 200 and "<svg" in out["svg"]
    assert call(server, "POST", "/api/diagram", {"kind": "mermaid", "source": "graph TD; A-->B"})[0] == 400
    assert call(server, "POST", "/api/diagram", {"source": "  "})[0] == 400


def test_grep_endpoint(server):
    from urllib.parse import quote

    status, out = call(server, "GET", "/api/grep?q=" + quote("return 1"))
    assert status == 200 and out["hits"] == [{"path": "pkg/a.py", "line": 2, "text": "return 1"}]
    assert out["truncated"] is False
    assert call(server, "GET", "/api/grep?q=")[0] == 400
    assert call(server, "GET", "/api/grep?q=" + quote("RETURN 1") + "&case=1")[1]["hits"] == []


def test_texts_batch(server, tree):
    (tree / "skills" / "one").mkdir(parents=True)
    (tree / "skills" / "two").mkdir()
    (tree / "skills" / "one" / "SKILL.md").write_text("---\nname: one\n---\n\nDo one.\n")
    (tree / "skills" / "two" / "SKILL.md").write_text("---\nname: two\n---\n\nDo two.\n")
    status, body = call(
        server,
        "POST",
        "/api/texts",
        {"paths": ["skills/one/SKILL.md", "skills/two/SKILL.md", "blob.bin", "missing.md", "../x"]},
    )
    assert status == 200
    assert body["files"][0]["content"].startswith("---\nname: one")
    assert body["files"][1] == {
        "path": "skills/two/SKILL.md",
        "kind": "text",
        "content": "---\nname: two\n---\n\nDo two.\n",
    }
    assert body["files"][2]["kind"] == "binary" and "content" not in body["files"][2]
    assert body["files"][3]["error"]
    assert ".." in body["files"][4]["error"]
    assert call(server, "POST", "/api/texts", {"paths": "nope"})[0] == 400
    assert call(server, "POST", "/api/texts", {"paths": ["a"] * 401})[0] == 400


def test_git_endpoints(server, repo):
    status, log = call(server, "GET", "/api/git/log?whole=1")
    assert status == 200 and log["commits"][0]["subject"] == "init"
    status, diff = call(server, "GET", f"/api/git/show?whole=1&commit={log['commits'][0]['short']}")
    assert status == 200 and "init" in diff


def test_context_roundtrip(server, capsys):
    call(
        server,
        "POST",
        "/api/context",
        {"paths": ["pkg/a.py", "README.md"], "lines": [1, 2], "quote": "def a():\n    return 1", "focus": "pkg/a.py"},
    )
    main(["context", "--url", server])
    assert capsys.readouterr().out == "pkg/a.py L1-2\nREADME.md\n    | def a():\n    |     return 1\n"
    call(server, "POST", "/api/context", {})
    main(["context", "--url", server])
    assert capsys.readouterr().out == "nothing selected\n"


def test_edits_with_window(server, tree, capsys):
    ws = Handler.ws
    ws.scan()
    ws.write_file("README.md", "new\n", ws.read_file("README.md")["hash"], False)
    p = tree / "README.md"
    os.utime(p, (time.time() + 5, time.time() + 5))
    ws.scan()
    main(["edits", "-C", str(tree), "--url", server])
    assert "saved in the editor (1):\n  README.md  (just now)" in capsys.readouterr().out
    main(["edits", "-C", str(tree / "pkg"), "--url", server])
    assert "the window at" in capsys.readouterr().out


def _remote_setup(repo, tmp_path, branch):
    bare = tmp_path / "bare.git"
    bare.mkdir()
    git(bare, "init", "--bare", "-q")
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", branch)
    other = tmp_path / "other"
    git(tmp_path, "clone", "--quiet", str(bare), str(other))
    git(other, "config", "user.email", "test@example.com")
    git(other, "config", "user.name", "test")
    return bare, other


def test_sync_endpoint(server, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(Handler, "ws", _ws(str(repo), "", [], False), raising=False)
    branch = git(repo, "branch", "--show-current").strip()
    bare, other = _remote_setup(repo, tmp_path, branch)

    status, info = call(server, "GET", "/api/sync")
    assert status == 200 and info["proj"]["branch"] == branch and info["proj"]["remotes"] == ["origin"]

    # the remote side commits something
    (other / "pkg" / "c.py").write_text("def c():\n    return 3\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "agent: add c.py")
    git(other, "push", "-q", "origin", branch)

    # the local side has an uncommitted edit
    (repo / "README.md").write_text("# proj\n\nchanged by the user.\n")

    status, out = call(server, "POST", "/api/sync")
    assert status == 200
    assert len(out["repos"]) == 1
    r = out["repos"][0]
    assert r["name"] == "proj" and r["repo"] == str(repo) and r["branch"] == branch
    assert r["ok"] is True and r["error"] == ""
    assert r["committed"] == 1 and r["incoming"] == 1 and r["pushed"] == 1
    assert r["conflicts"] == []
    assert (repo / "pkg" / "c.py").read_text() == "def c():\n    return 3\n"
    log = git(bare, "log", "--format=%s")
    assert "init" in log and "agent: add c.py" in log and log.count("treedit sync") == 1


def test_sync_pushes_conflicts_for_the_remote(server, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(Handler, "ws", _ws(str(repo), "", [], False), raising=False)
    branch = git(repo, "branch", "--show-current").strip()
    bare, other = _remote_setup(repo, tmp_path, branch)

    (other / "README.md").write_text("# proj\n\nagent side.\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "agent: side")
    git(other, "push", "-q", "origin", branch)

    (repo / "README.md").write_text("# proj\n\nuser side.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "user: side")

    status, out = call(server, "POST", "/api/sync")
    assert status == 200
    r = out["repos"][0]
    assert r["ok"] is True and r["published"] == ["README.md"] and r["conflicts"] == []
    assert r["committed"] == 0 and r["incoming"] == 1 and r["pushed"] >= 1
    text = (repo / "README.md").read_text()
    assert "<<<<<<<" in text and "user side" in text and "agent side" in text
    assert any(s.startswith("user: sync conflict") for s in git(bare, "log", "--format=%s").splitlines())
    # a plain pull mode is still available
    assert call(server, "POST", "/api/sync", {"publish": "no"})[0] == 400


def test_sync_needs_a_remote(server, repo, monkeypatch):
    monkeypatch.setattr(Handler, "ws", _ws(str(repo), "", [], False), raising=False)
    status, info = call(server, "GET", "/api/sync")
    assert status == 200 and info["proj"]["branch"] and info["proj"]["remotes"] == []
    status, out = call(server, "POST", "/api/sync")
    assert status == 200
    assert out["repos"][0]["error"] == "no remote" and out["repos"][0]["ok"] is False


def test_sync_outside_git(server):
    status, info = call(server, "GET", "/api/sync")
    assert status == 200 and info["proj"]["state"] == "not-git" and info["proj"]["branch"] == ""
    status, out = call(server, "POST", "/api/sync")
    assert status == 200
    assert out["repos"][0]["error"] == "not a git repository" and out["repos"][0]["ok"] is False
    assert call(server, "POST", "/api/sync", {"commit": "yes"})[0] == 400


def test_sync_mounts_status(server, tree, tmp_path, monkeypatch):
    monkeypatch.setattr(Handler, "ws", _ws(str(tree), "", [], False), raising=False)
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.md").write_text("x\n")
    assert call(server, "POST", "/api/mount", {"path": str(other)})[0] == 200
    status, info = call(server, "GET", "/api/sync")
    assert status == 200 and set(info) == {"proj", "other", "*"}
    assert info["proj"]["remotes"] == [] and info["other"]["remotes"] == []


def test_sync_cli(repo, tmp_path, capsys):
    branch = git(repo, "branch", "--show-current").strip()
    bare, _ = _remote_setup(repo, tmp_path, branch)
    (repo / "user.txt").write_text("me\n")
    main(["sync", "-C", str(repo)])
    out = capsys.readouterr().out
    assert "committed 1 file" in out and "pushed 1 commit" in out
    assert git(bare, "log", "--format=%s").count("treedit sync") == 1
    main(["sync", "-C", str(repo)])
    assert "nothing to pull" in capsys.readouterr().out


def test_quit(server):
    assert call(server, "POST", "/api/quit", {})[1] == {"ok": True}


def test_terminal(server, monkeypatch, tree):
    terms = Sessions(str(tree), {"SHELL": "/bin/sh", "PATH": os.environ.get("PATH", ""), "PS1": "$ "}, "echo hi-there")
    term = terms.get("1")
    monkeypatch.setattr(Handler, "terms", terms)
    host, port = server.removeprefix("http://").split(":")
    token = Handler.token

    def handshake(origin, tok=token):
        s = socket.create_connection((host, int(port)), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall(
            (
                f"GET /api/term?token={tok} HTTP/1.1\r\nHost: {host}:{port}\r\nOrigin: {origin}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n\r\n"
            ).encode()
        )
        return s

    s = handshake("http://evil.example")
    assert b"403" in s.recv(1024)
    s.close()
    s = handshake(f"http://{host}:{port}", tok="wrong")
    assert b"403" in s.recv(1024)
    s.close()
    s = handshake(f"http://{host}:{port}")
    data = b""
    deadline = time.time() + 10
    while b"hi-there" not in data.split(b"echo hi-there")[-1] and time.time() < deadline:
        data += s.recv(65536)
    assert b"101 Switching Protocols" in data and b'"hello"' in data
    assert b"hi-there" in data.split(b"echo hi-there")[-1]

    def send(op, payload):
        mask = b"\0\0\0\0"
        frame = ws_frame(op, payload)
        s.sendall(
            frame[:1] + bytes([frame[1] | 0x80]) + frame[2 : 2 + (len(frame) - 2 - len(payload))] + mask + payload
        )

    send(1, json.dumps({"t": "resize", "rows": 30, "cols": 100}).encode())
    send(1, b"not json")
    send(1, json.dumps({"t": "in", "d": "echo again\r"}).encode())
    send(9, b"ping")
    deadline, data = time.time() + 10, b""
    while (b"\x8a\x04ping" not in data or b"again" not in data) and time.time() < deadline:
        data += s.recv(65536)
    assert b"\x8a\x04ping" in data and b"again" in data
    assert term.size == (30, 100)
    send(8, b"")
    s.close()
    term.stop()
    assert not term.alive


def test_open_headless(tree, monkeypatch, capsys):
    from treedit.cli import open_editor

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(Handler, "window", None)
    monkeypatch.setattr(Handler, "terms", None)
    t = threading.Thread(
        target=open_editor,
        args=(str(tree), port, "127.0.0.1", False, True, "", "", [], False, False, ["notes"]),
        daemon=True,
    )
    t.start()
    base, deadline = f"http://127.0.0.1:{port}", time.time() + 5
    while time.time() < deadline:
        try:
            assert call(base, "GET", "/api/version")[0] == 200
            break
        except OSError:
            time.sleep(0.05)
    assert Handler.terms is not None and Handler.agent == ""
    assert call(base, "POST", "/api/quit", {})[1] == {"ok": True}
    t.join(5)
    assert not t.is_alive()
    out = capsys.readouterr().out
    assert f"open   {base}/" in out and "agent  shell" in out


def test_terminal_sessions(server, monkeypatch, tree):
    terms = Sessions(str(tree), {"SHELL": "/bin/sh", "PATH": os.environ.get("PATH", ""), "PS1": "$ "}, "")
    monkeypatch.setattr(Handler, "terms", terms)
    assert call(server, "GET", "/api/terms")[1]["terms"] == [
        {"id": "1", "label": "sh", "agent": "", "alive": False, "root": str(tree), "dir": "", "mount": "proj"}
    ]
    status, out = call(server, "POST", "/api/term/new", {"agent": "echo second-pane"})
    assert status == 200 and out["id"] == "2" and [t["label"] for t in out["terms"]] == ["sh", "echo second-pane"]
    host, port = server.removeprefix("http://").split(":")
    s = socket.create_connection((host, int(port)), timeout=5)
    s.sendall(
        (
            f"GET /api/term?token={Handler.token}&id=2 HTTP/1.1\r\nHost: {host}:{port}\r\n"
            f"Origin: http://{host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
        ).encode()
    )
    data, deadline = b"", time.time() + 10
    while b"second-pane" not in data.split(b"echo second-pane")[-1] and time.time() < deadline:
        data += s.recv(65536)
    assert b'"label": "echo second-pane"' in data and terms.get("2").alive and not terms.get("1").alive
    assert [t["id"] for t in call(server, "POST", "/api/term/close", {"id": "2"})[1]["terms"]] == ["1"]
    data, deadline = b"", time.time() + 5
    while b'"closed"' not in data and time.time() < deadline:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    assert b'"closed"' in data
    s.close()
    assert call(server, "POST", "/api/term/close", {"id": "2"})[0] == 404
    assert call(server, "GET", "/api/term?id=9&token=" + Handler.token)[0] == 404
    terms.stop()


def test_make_targets_and_run(server, monkeypatch, tree):
    makefile = """\
ROOT ?= .
.DEFAULT_GOAL := help
.PHONY: help test
help: ## Show this help
\t@echo hi
test lint: pkg ## Run the checks
\t@true
$(VENV)/bin/tool: pyproject.toml
foo%: ; @true
"""
    (tree / "pkg" / "Makefile").write_text(makefile)
    status, out = call(server, "GET", "/api/make?path=pkg/Makefile")
    assert status == 200
    assert out["path"] == "pkg/Makefile" and out["name"] == "Makefile"
    assert out["dir"] == str((tree / "pkg").resolve())
    assert out["targets"] == [
        {"name": "help", "desc": "Show this help", "default": True},
        {"name": "test", "desc": "Run the checks", "default": False},
        {"name": "lint", "desc": "Run the checks", "default": False},
    ]
    assert call(server, "GET", "/api/make?path=README.md")[0] == 400
    assert call(server, "GET", "/api/make?path=pkg/nope.mk")[0] == 404
    assert call(server, "POST", "/api/make/run", {"path": "pkg/Makefile", "target": "help"})[0] == 404
    if shutil.which("make") is None:
        pytest.skip("make is not installed")
    terms = Sessions(str(tree), {"SHELL": "/bin/sh", "PATH": os.environ.get("PATH", ""), "TREEDIT_ROOT": str(tree)}, "")
    monkeypatch.setattr(Handler, "terms", terms)
    status, out = call(server, "POST", "/api/make/run", {"path": "pkg/Makefile", "target": "help"})
    assert status == 200 and out["id"] == "1" and out["reused"] is True
    t = terms.get("1")
    assert t.proc is None and t.reuse  # not started yet: the command waits for the first prompt
    assert str((tree / "pkg").resolve()).encode() in t.pending and t.pending.endswith(b")\r")
    assert len(out["terms"]) == 1 and out["terms"][0]["label"] == "sh"
    t.start()
    deadline = time.time() + 10
    while b"hi" not in t.buf and time.time() < deadline:
        time.sleep(0.05)
    assert b"hi" in t.buf
    while not t.at_prompt and time.time() < deadline:
        time.sleep(0.05)
    assert t.at_prompt
    status, out = call(server, "POST", "/api/make/run", {"path": "pkg/Makefile", "target": "help"})
    assert status == 200 and out["reused"] is True and out["id"] == "1"
    deadline = time.time() + 10
    while t.buf.count(b"hi") < 2 and time.time() < deadline:
        time.sleep(0.05)
    assert t.buf.count(b"hi") >= 2
    assert call(server, "POST", "/api/make/run", {"path": "pkg/Makefile", "target": "nope"})[0] == 400
    terms.stop()

    # an agent preset is not a shell: the first make run needs a session of its own, which is then reused
    terms = Sessions(str(tree), {"SHELL": "/bin/sh", "PATH": os.environ.get("PATH", "")}, "claude")
    monkeypatch.setattr(Handler, "terms", terms)
    status, out = call(server, "POST", "/api/make/run", {"path": "pkg/Makefile", "target": "help"})
    assert status == 200 and out["id"] == "2" and out["reused"] is False
    t = terms.get("2")
    assert t.cwd == str((tree / "pkg").resolve()) and t.root == str(tree.resolve())
    assert " -f Makefile help)" in t.agent and t.label() == "make help" and t.reuse
    assert t.env["TREEDIT_ROOT"] == str(tree)
    second = next(x for x in out["terms"] if x["id"] == "2")
    assert second["label"] == "make help" and second["dir"] == "pkg" and second["mount"] == "proj"
    status, out = call(server, "POST", "/api/make/run", {"path": "pkg/Makefile", "target": "test"})
    assert status == 200 and out["reused"] is True and out["id"] == "2"
    assert t.name == "make test" and b"test" in t.pending
    terms.stop()


def test_queue_round_trip(server, tree):
    assert call(server, "GET", "/api/queue")[1] == {
        "at": 0.0,
        "target": "",
        "notes": {},
        "feedback": [],
        "history": [],
        "held": [],
    }
    held = [{"key": "note:README.md", "kind": "note", "path": "README.md", "text": "keep"}]
    status, out = call(
        server,
        "POST",
        "/api/queue/rolled",
        {
            "target": "claude · #1",
            "notes": {"pkg": "the package"},
            "feedback": ["1"],
            "items": [{"key": "edit:pkg/b.py", "kind": "edit", "path": "pkg/b.py"}],
            "held": held,
        },
    )
    assert status == 200 and out["at"] > 0
    assert out["target"] == "claude · #1" and out["notes"] == {"pkg": "the package"}
    assert out["feedback"] == ["1"] and out["held"] == held
    assert out["history"] == [
        {
            "at": out["at"],
            "target": "claude · #1",
            "items": [{"key": "edit:pkg/b.py", "kind": "edit", "path": "pkg/b.py"}],
        }
    ]
    status, out = call(
        server,
        "POST",
        "/api/queue/rolled",
        {
            "target": "sh",
            "notes": {"pkg": "the package, again", "README.md": "readme"},
            "feedback": ["2"],
            "items": [],
            "held": [],
        },
    )
    assert status == 200 and out["target"] == "sh" and out["held"] == []
    assert out["notes"] == {"pkg": "the package, again", "README.md": "readme"}
    assert out["feedback"] == ["1", "2"] and [h["target"] for h in out["history"]] == ["sh", "claude · #1"]
    assert call(server, "GET", "/api/queue")[1] == out


def test_typst_compiles_to_pdf_and_opens(server, tree, monkeypatch, tmp_path):
    (tree / "doc.typ").write_text("#let x = 1\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "typst"
    exe.write_text(f"#!{sys.executable}\nimport sys\nopen(sys.argv[-1], 'wb').write(b'%PDF-1.4\\n')\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    status, out = call(server, "POST", "/api/typst", {"path": "doc.typ"})
    assert status == 200 and out == {"path": "doc.pdf", "output": ""}
    assert (tree / "doc.pdf").read_bytes().startswith(b"%PDF")
    assert "doc.pdf" in [n["name"] for n in call(server, "GET", "/api/tree")[1]["tree"]["children"]]
    assert call(server, "POST", "/api/typst", {"path": "README.md"})[0] == 400
    assert call(server, "POST", "/api/typst", {"path": "missing.typ"})[0] == 404
    exe.write_text(f"#!{sys.executable}\nimport sys\nsys.stderr.write('error: broken document\\n')\nsys.exit(1)\n")
    status, out = call(server, "POST", "/api/typst", {"path": "doc.typ"})
    assert status == 400 and "broken document" in out["error"]
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert call(server, "POST", "/api/typst", {"path": "doc.typ"})[0] == 404


def test_typst_pdf_stays_visible_when_gitignored(repo, monkeypatch, tmp_path):
    (repo / "doc.typ").write_text("#let x = 1\n")
    (repo / ".gitignore").write_text("*.pdf\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "typst"
    exe.write_text(f"#!{sys.executable}\nimport sys\nopen(sys.argv[-1], 'wb').write(b'%PDF-1.4\\n')\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    ws = _ws(str(repo), "", [], False)
    assert ws.compile_typst("doc.typ")["path"] == "doc.pdf"
    assert "doc.pdf" in [n["name"] for n in ws.scan()["children"]]


def test_mount_from_the_page(server, tree, tmp_path):
    assert call(server, "PUT", "/api/note", {"path": "pkg", "note": "package"})[0] == 200
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.md").write_text("x\n")
    status, body = call(server, "POST", "/api/mount", {"path": str(other)})
    assert status == 200 and body["promoted"] == "proj" and body["name"] == "other"
    assert body["mounts"] == [
        {"name": "proj", "root": str(tree.resolve())},
        {"name": "other", "root": str(other.resolve())},
    ]
    t = call(server, "GET", "/api/tree")[1]
    assert t["tree"]["multi"] and t["root"] == "proj + other" and t["notes"]["proj/pkg"] == "package"
    assert (tree / ".treenotes.json").exists()
    third = tmp_path / "third"
    third.mkdir()
    again = call(server, "POST", "/api/mount", {"path": str(third)})[1]
    assert again["promoted"] is None and [m["name"] for m in again["mounts"]] == ["proj", "other", "third"]
    assert call(server, "POST", "/api/mount", {"path": str(other)})[0] == 400
    assert call(server, "POST", "/api/mount", {"path": str(tmp_path / "missing")})[0] == 400
    assert call(server, "POST", "/api/mount", {})[0] == 400


def test_terminal_belongs_to_a_tree(server, monkeypatch, tree, tmp_path):
    terms = Sessions(str(tree), {"SHELL": "/bin/sh", "PATH": os.environ.get("PATH", ""), "TREEDIT_ROOT": str(tree)}, "")
    monkeypatch.setattr(Handler, "terms", terms)
    other = tmp_path / "other"
    other.mkdir()
    assert call(server, "POST", "/api/mount", {"path": str(other)})[0] == 200
    status, out = call(server, "POST", "/api/term/new", {"agent": "echo on-other", "root": "other"})
    assert status == 200
    second = next(t for t in out["terms"] if t["id"] == "2")
    assert second["root"] == str(other.resolve()) and second["mount"] == "other" and second["alive"] is False
    assert terms.get("2").cwd == str(other.resolve())
    assert terms.get("2").env["TREEDIT_ROOT"] == str(other.resolve())
    assert terms.get("2").env["TREEDIT_NOTES"] == str(other.resolve() / ".treenotes.json")
    assert str(tree.resolve()) in terms.get("2").env["TREEDIT_ROOTS"].split(os.pathsep)
    assert str(other.resolve()) in terms.get("2").env["TREEDIT_ROOTS"].split(os.pathsep)
    assert terms.get("1").env["TREEDIT_ROOT"] == str(tree)  # already running: its env stays
    assert call(server, "POST", "/api/term/new", {"agent": "x", "root": "nope"})[0] == 400
    first = next(t for t in call(server, "GET", "/api/terms")[1]["terms"] if t["id"] == "1")
    assert first["root"] == str(tree) and first["mount"] == "proj"
    terms.stop()


FAKE_SSH = r'''#!PYTHON
"""Stands in for ssh: `-N -L l:lport:h:rport` relays a local port, else runs the last argument locally."""
import socket, subprocess, sys, threading
args = sys.argv[1:]
if "-N" in args:
    _, lport, _, rport = args[args.index("-L") + 1].split(":")
    srv = socket.create_server(("127.0.0.1", int(lport)))
    def pipe(a, b):
        try:
            while data := a.recv(65536):
                b.sendall(data)
        except OSError:
            pass
        finally:
            b.close()
    while True:
        c, _ = srv.accept()
        r = socket.create_connection(("127.0.0.1", int(rport)))
        threading.Thread(target=pipe, args=(c, r), daemon=True).start()
        threading.Thread(target=pipe, args=(r, c), daemon=True).start()
sys.exit(subprocess.call(["sh", "-c", args[-1]]))
'''


def test_remote_argv(monkeypatch):
    from treedit.cli import remote_argv

    monkeypatch.delenv("TREEDIT_REMOTE_CMD", raising=False)
    argv = remote_argv(
        "me@box", ["~/my proj", "/srv/x"], 8765, "claude --x", "", ["*.log"], False, True, ["notes"], True
    )
    assert argv[:-1] == ["ssh", "-tt", "-o", "ServerAliveInterval=15", "me@box"]
    assert argv[-1] == (
        "env TREEDIT_IN_APP=1 treedit open ~/'my proj' /srv/x --headless --port 8765 "
        "--agent 'claude --x' --ignore '*.log' --no-gitignore"
    )


def test_open_remote(tree, tmp_path, monkeypatch, capsys):
    import sys
    from treedit.cli import open_editor

    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "ssh").write_text(FAKE_SSH.replace("PYTHON", sys.executable))
    (bin_ / "ssh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("TREEDIT_REMOTE_CMD", f"{sys.executable} -m treedit")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    t = threading.Thread(
        target=open_editor,
        args=(str(tree), port, "127.0.0.1", False, True, "", "", [], False, False, ["notes"], "box"),
        daemon=True,
    )
    t.start()
    out, deadline, base = "", time.time() + 20, None
    while time.time() < deadline and base is None:
        out += capsys.readouterr().out
        for line in out.splitlines():
            if "(tunnel to box:" in line:
                base = line.split()[1].rstrip("/")
        time.sleep(0.05)
    assert base and base != f"http://127.0.0.1:{port}"  # the local end of the tunnel, not the server
    assert call(base, "GET", "/api/tree")[0] == 200
    assert call(base, "POST", "/api/quit", {})[1] == {"ok": True}
    t.join(10)
    assert not t.is_alive()


def test_create_at_depth_matches_cli(server, tree, capsys):
    from treedit.cli import main

    st, plan = call(server, "POST", "/api/create", {"paths": ["pkg/x/y/z.md"], "dry_run": True})
    assert st == 200 and plan["log"] is None and not (tree / "pkg/x").exists()
    assert plan["lines"] == ["would create dir  pkg/x/", "would create dir  pkg/x/y/", "would create file pkg/x/y/z.md"]
    main(["new", "-C", str(tree), "pkg/x/y/z.md", "-n"])
    assert capsys.readouterr().out.splitlines() == plan["lines"]  # the CLI and the window say the same
    st, r = call(server, "POST", "/api/create", {"paths": ["pkg/x/y/z.md"]})
    assert [e["action"] for e in r["entries"]] == ["created"] * 3 and r["log"]["seq"] == 1
    assert r["lines"][-1] == "logged as #1 (undo: treedit undo 1)"
    st, r = call(server, "POST", "/api/create", {"paths": ["pkg/x/y/z.md"]})
    assert st == 409 and "already exists" in r["error"]
    st, r = call(server, "POST", "/api/create", {"paths": ["README.md/q"]})
    assert st == 409 and "is a file, not a folder" in r["error"]
    st, r = call(server, "POST", "/api/create", {"paths": ["d1/d2"]})
    assert r["lines"][:2] == ["created      dir  d1/", "created      dir  d1/d2/"]
    st, u = call(server, "POST", "/api/undo", {"seq": 1})
    assert st == 200 and u["lines"] == ["file pkg/x/y/z.md removed", "dir pkg/x/y removed", "dir pkg/x removed"]
    assert not (tree / "pkg/x").exists() and (tree / "d1/d2").is_dir()
    main(["log", "-C", str(tree)])
    assert "undo #1" in capsys.readouterr().out
    assert call(server, "POST", "/api/undo", {"seq": 1})[0] == 409


def test_create_in_mounts(tmp_path):
    from treedit.cli import Mounts, _ws, new_report

    for n in ("one", "two"):
        (tmp_path / n).mkdir()
    m = Mounts([_ws(str(tmp_path / "one"), "", [], False), _ws(str(tmp_path / "two"), "", [], False)])
    rep = new_report(*m.create_paths(["two/a/b.txt"]), False)
    assert rep["lines"][:2] == ["created      dir  two/a/", "created      file two/a/b.txt"]
    assert (tmp_path / "two/a/b.txt").exists()
    m.undo(None, "two/a")
    assert not (tmp_path / "two/a").exists()


def test_layout_sidecar(server, tree):
    assert call(server, "GET", "/api/layout?path=d.md")[1] == {"nodes": {}}
    assert call(server, "PUT", "/api/layout", {"path": "d.md", "nodes": {"A": [1.4, -2.6], "B": [3, 4]}})[0] == 200
    assert call(server, "GET", "/api/layout?path=d.md")[1] == {"nodes": {"A": [1, -3], "B": [3, 4]}}
    side = tree / ".treedit-layout.json"
    assert side.read_text() == '{"version": 1, "files": {\n  "d.md": {"A":[1,-3],"B":[3,4]}\n}}\n'
    assert "treedit-layout" not in json.dumps(call(server, "GET", "/api/tree")[1]["tree"])  # hidden like .treedit-*
    assert call(server, "PUT", "/api/layout", {"path": "d.md", "nodes": {"A": "x"}})[0] == 400
    assert call(server, "PUT", "/api/layout", {"path": "d.md", "nodes": {}})[0] == 200
    assert not side.exists()
