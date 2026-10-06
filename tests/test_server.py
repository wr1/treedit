import base64
import json
import os
import socket
import threading
import time
from urllib.error import HTTPError as URLHTTPError
from urllib.request import Request, urlopen

import pytest

from treedit.cli import Handler, Server, _ws, main
from treedit.term import Terminal, ws_frame


@pytest.fixture
def server(tree, monkeypatch):
    monkeypatch.setattr(Handler, "ws", _ws(str(tree), "", [], False), raising=False)
    monkeypatch.setattr(Handler, "term", None)
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
    assert call(server, "GET", "/logo.svg")[1].startswith("<svg")
    assert call(server, "GET", "/vendor/nope.js")[0] == 404


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
    assert "proj/" in call(server, "GET", "/api/export")[1]
    assert "lines" not in call(server, "GET", "/api/export?counts=0")[1]
    assert call(server, "GET", "/api/changes")[1]["root"] == str(tree)


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


def test_git_endpoints(server, repo):
    status, log = call(server, "GET", "/api/git/log?whole=1")
    assert status == 200 and log["commits"][0]["subject"] == "init"
    status, diff = call(server, "GET", f"/api/git/show?whole=1&commit={log['commits'][0]['short']}")
    assert status == 200 and "init" in diff


def test_context_roundtrip(server, capsys):
    call(server, "POST", "/api/context", {"paths": ["pkg/a.py", "README.md"], "lines": [1, 2],
                                          "quote": "def a():\n    return 1", "focus": "pkg/a.py"})
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


def test_quit(server):
    assert call(server, "POST", "/api/quit", {})[1] == {"ok": True}


def test_terminal(server, monkeypatch, tree):
    term = Terminal(str(tree), {"SHELL": "/bin/sh", "PATH": os.environ.get("PATH", ""), "PS1": "$ "}, "echo hi-there")
    monkeypatch.setattr(Handler, "term", term)
    host, port = server.removeprefix("http://").split(":")
    token = Handler.token

    def handshake(origin, tok=token):
        s = socket.create_connection((host, int(port)), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET /api/term?token={tok} HTTP/1.1\r\nHost: {host}:{port}\r\nOrigin: {origin}\r\n"
                   f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n\r\n").encode())
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
        s.sendall(frame[:1] + bytes([frame[1] | 0x80]) + frame[2:2 + (len(frame) - 2 - len(payload))] + mask + payload)

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
    monkeypatch.setattr(Handler, "term", None)
    t = threading.Thread(target=open_editor, args=(str(tree), port, "127.0.0.1", False, True, "", "", [], False,
                                                   False, ["notes"]), daemon=True)
    t.start()
    base, deadline = f"http://127.0.0.1:{port}", time.time() + 5
    while time.time() < deadline:
        try:
            assert call(base, "GET", "/api/version")[0] == 200
            break
        except OSError:
            time.sleep(0.05)
    assert Handler.term is not None and Handler.agent == ""
    assert call(base, "POST", "/api/quit", {})[1] == {"ok": True}
    t.join(5)
    assert not t.is_alive()
    out = capsys.readouterr().out
    assert f"open   {base}/" in out and "agent  shell" in out
