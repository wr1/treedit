import json
import sys

import pytest

from treedit.cli import _ws, main


def run(capsys, *argv):
    main(list(argv))
    return capsys.readouterr().out


def test_print(capsys, tree):
    out = run(capsys, "print", str(tree))
    assert out.startswith("proj/") and "README.md" in out
    assert "\033[" in run(capsys, "print", str(tree), "--color")
    assert "lines" not in run(capsys, "print", str(tree), "--no-counts")


def test_print_not_a_folder(tmp_path):
    with pytest.raises(SystemExit, match="is not a folder"):
        main(["print", str(tmp_path / "nope")])


def test_annotations(capsys, tree):
    run(capsys, "annotation", "-C", str(tree), "set", "pkg", "the package")
    run(capsys, "annotation", "-C", str(tree), "set", "old", "stale note")
    assert run(capsys, "annotation", "-C", str(tree), "get", "pkg") == "the package\n"
    assert run(capsys, "annotation", "-C", str(tree), "ls") == "old\tstale note  (gone)\npkg\tthe package\n"
    run(capsys, "annotation", "-C", str(tree), "mv", "pkg", "lib")
    with pytest.raises(SystemExit) as e:
        main(["annotation", "-C", str(tree), "get", "pkg"])
    assert e.value.code == 1


def test_feedback(capsys, tree):
    r = str(tree)
    assert run(capsys, "fb", "-C", r, "add", "tidy", "pkg/a.py", "--lines", "1-2") == "#1 added on pkg/a.py  (log #1)\n"
    assert (
        run(capsys, "fb", "-C", r, "add", "merge", "pkg/a.py", "pkg/b.py")
        == "#2 added on pkg/a.py, pkg/b.py  (log #2)\n"
    )
    out = run(capsys, "fb", "-C", r, "ls")
    assert "#1 L1-2  open  pkg/a.py" in out and "    | def a():" in out and "    tidy" in out
    run(capsys, "fb", "-C", r, "reply", "1", "renamed\nand moved", "--done")
    assert "#1" not in run(capsys, "fb", "-C", r, "ls")
    out = run(capsys, "fb", "-C", r, "ls", "--all")
    assert "reply: renamed\n           and moved" in out
    run(capsys, "fb", "-C", r, "reopen", "1")
    run(capsys, "fb", "-C", r, "done", "2")
    run(capsys, "fb", "-C", r, "rm", "2")
    assert [f["id"] for f in _ws(r, "", [], False).read_feedback()] == [1]
    with pytest.raises(SystemExit, match="no feedback #7"):
        main(["fb", "-C", r, "rm", "7"])


def test_edits_without_window(capsys, tree):
    out = run(capsys, "edits", "-C", str(tree))
    assert "unsaved in the editor: none" in out and "saved in the editor: unknown" in out
    _ws(str(tree), "", [], False).set_draft("README.md", {"diff": "-a\n+b\n"})
    out = run(capsys, "edits", "-C", str(tree), "--url", "http://127.0.0.1:9")
    assert "README.md  (draft, just now)" in out and "    +b" in out and "no treedit window at" in out


def test_context_without_window():
    with pytest.raises(SystemExit, match="no treedit window"):
        main(["context", "--url", "http://127.0.0.1:9"])


def test_skill(capsys, tmp_path):
    out = run(capsys, "skill", "show")
    assert out.startswith("---\nname: treedit") and "treedit fb ls" in out
    assert run(capsys, "skill", "install", "--dir", str(tmp_path)).strip() == str(tmp_path / "treedit" / "SKILL.md")
    assert (tmp_path / "treedit" / "SKILL.md").read_text() == out
    with pytest.raises(SystemExit, match="neither"):
        main(["skill", "install"])
    run(capsys, "skill", "install", "--claude")


def test_schema(capsys):
    with pytest.raises(SystemExit):
        main(["-j"])
    out = capsys.readouterr().out
    assert json.loads(out)["name"] == "treedit"


def test_module_entry(tree):
    import subprocess

    r = subprocess.run(
        [sys.executable, "-m", "treedit", "print", str(tree), "--no-counts"], capture_output=True, text=True, check=True
    )
    assert "pkg/" in r.stdout


def test_new_at_depth(capsys, tree):
    r = str(tree)
    out = run(capsys, "new", "-C", r, "a/b/c/file.ext", "--dry-run")
    assert out.split("\n")[0] == "would create dir  a/" and "would create file a/b/c/file.ext" in out
    assert not (tree / "a").exists()
    out = run(capsys, "new", "-C", r, "a/b/c/file.ext", "a/b/other.md", "pkg/sub/x.py")
    assert out.splitlines() == [
        "created      dir  a/",
        "created      dir  a/b/",
        "created      dir  a/b/c/",
        "created      file a/b/c/file.ext",
        "created      file a/b/other.md",
        "created      dir  pkg/sub/",
        "created      file pkg/sub/x.py",
        "logged as #1 (undo: treedit undo 1)",
    ]
    assert (tree / "a/b/c/file.ext").read_text() == ""
    assert run(capsys, "new", "-C", r, "d/e", "--dir").startswith("created      dir  d/\ncreated      dir  d/e/\n")
    assert (tree / "d/e").is_dir()


def test_new_existing(capsys, tree):
    r = str(tree)
    (tree / "README.md").write_text("keep\n")
    with pytest.raises(SystemExit, match="README.md already exists"):
        main(["new", "-C", r, "README.md"])
    assert run(capsys, "new", "-C", r, "README.md", "-e") == "exists       file README.md\n"
    assert (tree / "README.md").read_text() == "keep\n"
    assert run(capsys, "new", "-C", r, "pkg", "--dir", "-e") == "exists       dir  pkg/\n"
    with pytest.raises(SystemExit, match="pkg exists as a folder"):
        main(["new", "-C", r, "pkg", "-e"])
    with pytest.raises(SystemExit, match="README.md is a file, not a folder"):
        main(["new", "-C", r, "README.md/x"])
    with pytest.raises(SystemExit, match="both a file and a folder"):
        main(["new", "-C", r, "z", "z/y"])
    with pytest.raises(SystemExit):
        main(["new", "-C", r, "../out.txt"])
    # nothing half-done: a failing later path leaves the earlier ones uncreated
    with pytest.raises(SystemExit):
        main(["new", "-C", r, "fresh/one", "README.md/x"])
    assert not (tree / "fresh").exists() and not (tree.parent / "out.txt").exists()


def test_confirmations_and_json(capsys, tree):
    r = str(tree)
    assert run(capsys, "annotation", "-C", r, "set", "pkg", "the package") == "set annotation on pkg  (log #1)\n"
    assert run(capsys, "annotation", "-C", r, "mv", "pkg", "lib").startswith(
        "moved annotations and feedback pkg -> lib"
    )
    assert run(capsys, "annotation", "-C", r, "rm", "lib") == "removed annotation on lib  (log #3)\n"
    run(capsys, "fb", "-C", r, "add", "x", "README.md")
    assert run(capsys, "fb", "-C", r, "reply", "1", "ok") == "#1 replied  (log #5)\n"
    assert run(capsys, "fb", "-C", r, "done", "1") == "#1 done  (log #6)\n"
    assert run(capsys, "fb", "-C", r, "reopen", "1") == "#1 reopened  (log #7)\n"
    out = json.loads(run(capsys, "fb", "-C", r, "add", "y", "pkg/b.py", "--json"))
    assert out["op"] == "fb add" and out["id"] == 2 and out["log"]["seq"] == 8
    assert [f["id"] for f in json.loads(run(capsys, "--json", "fb", "-C", r, "ls"))] == [1, 2]
    assert json.loads(run(capsys, "annotation", "-C", r, "ls", "--json")) == []
    new = json.loads(run(capsys, "new", "-C", r, "q/w.txt", "-n", "--json"))
    assert new["dry_run"] and [e["path"] for e in new["entries"]] == ["q", "q/w.txt"] and new["log"] is None
    run(capsys, "annotation", "-C", r, "set", "pkg", "p")
    assert json.loads(run(capsys, "annotation", "-C", r, "get", "pkg", "--json")) == {"path": "pkg", "annotation": "p"}


def test_strict_validation(capsys, tree):
    r = str(tree)
    for argv, msg in [
        (["annotation", "-C", r, "mv", "nope", "x"], "no annotations or feedback on nope"),
        (["annotation", "-C", r, "rm", "nope"], "no annotation on nope"),
        (["fb", "-C", r, "add", "t", "missing.py"], "missing.py not found"),
        (["fb", "-C", r, "add", "t", "pkg/b.py", "-l", "1-3"], "out of range: pkg/b.py has 1 line"),
        (["fb", "-C", r, "add", "t", "pkg/b.py", "-l", "0-1"], "out of range"),
        (["fb", "-C", r, "add", "t", "pkg/b.py", "-l", "x"], "--lines must be A-B"),
        (["fb", "-C", r, "add", "t", "pkg", "-l", "1-1"], "pkg is not a file"),
        (["fb", "-C", r, "add", "t", "pkg/a.py", "pkg/b.py", "-l", "1-1"], "exactly one file"),
    ]:
        with pytest.raises(SystemExit, match=msg) as e:
            main(argv)
        assert e.value.code != 0
    assert run(capsys, "fb", "-C", r, "add", "ok", "pkg/a.py", "-l", "5-6").startswith("#1 ")


def test_log_undo_restore(capsys, tree):
    r = str(tree)
    run(capsys, "annotation", "-C", r, "set", "pkg", "one")
    run(capsys, "annotation", "-C", r, "set", "pkg", "two")
    run(capsys, "fb", "-C", r, "add", "x", "README.md")
    run(capsys, "fb", "-C", r, "rm", "1")
    with pytest.raises(SystemExit, match="no feedback #1"):
        main(["fb", "-C", r, "done", "1"])
    assert run(capsys, "fb", "-C", r, "restore", "1") == "#1 restored  (log #5)\n"
    with pytest.raises(SystemExit, match="feedback #1 exists"):
        main(["fb", "-C", r, "restore", "1"])
    with pytest.raises(SystemExit, match="no deleted feedback #9"):
        main(["fb", "-C", r, "restore", "9"])
    # a removed id is never handed out again
    run(capsys, "fb", "-C", r, "rm", "1")
    assert run(capsys, "fb", "-C", r, "add", "y", "README.md").startswith("#2 ")
    log = run(capsys, "log", "-C", r)
    assert "annotation set: annotation pkg changed" in log and "fb rm: feedback #1 removed" in log
    assert len(json.loads(run(capsys, "log", "-C", r, "-n", "2", "--json"))) == 2
    assert run(capsys, "undo", "-C", r).startswith("undid #7: feedback #2 removed")
    assert run(capsys, "undo", "-C", r, "2") == "undid #2: annotation pkg changed  (log #9)\n"
    assert _ws(r, "", [], False).read_notes()["pkg"] == "one"
    with pytest.raises(SystemExit, match="already undone"):
        main(["undo", "-C", r, "2"])
    with pytest.raises(SystemExit, match="is an undo itself"):
        main(["undo", "-C", r, "9"])
    with pytest.raises(SystemExit, match="no log entry #99"):
        main(["undo", "-C", r, "99"])
    assert run(capsys, "undo", "-C", r, "1").startswith("undid #1: annotation pkg removed  (log #10)")
    run(capsys, "annotation", "-C", r, "set", "README.md", "r")
    run(capsys, "annotation", "-C", r, "set", "README.md", "s")
    with pytest.raises(SystemExit, match="annotation on README.md changed since"):
        main(["undo", "-C", r, "11"])
    assert "(undone)" in run(capsys, "log", "-C", r)
    entry = json.loads((tree / ".treenotes.log.jsonl").read_text().splitlines()[0])
    assert (
        entry["who"]
        and entry["at"]
        and entry["changes"][0] == {"kind": "note", "key": "pkg", "before": None, "after": "one"}
    )


def test_undo_who(capsys, tree, monkeypatch):
    monkeypatch.setenv("TREEDIT_WHO", "agent:claude")
    run(capsys, "annotation", "-C", str(tree), "set", "pkg", "x")
    assert "agent:claude  annotation set" in run(capsys, "log", "-C", str(tree))
    with pytest.raises(SystemExit, match="nothing to undo"):
        main(["undo", "-C", str(tree / "pkg")])


def test_undo_new(capsys, tree):
    r = str(tree)
    run(capsys, "new", "-C", r, "a/b/c.md", "a/d.txt")
    (tree / "a/d.txt").write_text("edited\n")
    with pytest.raises(SystemExit, match="a/d.txt changed since it was created"):
        main(["undo", "-C", r])
    assert (tree / "a/b/c.md").exists()  # all or nothing
    (tree / "a/d.txt").write_text("")
    (tree / "a/extra").write_text("mine")
    with pytest.raises(SystemExit, match="a/ is no longer empty"):
        main(["undo", "-C", r])
    (tree / "a/extra").unlink()
    (tree / "a/d.txt").unlink()  # already gone: fine
    out = run(capsys, "undo", "-C", r)
    assert out.startswith("undid #1: file a/b/c.md removed, dir a/b removed, dir a removed")
    assert not (tree / "a").exists() and (tree / "pkg").is_dir()
    # undo only removes what `new` created: existing parents stay
    run(capsys, "new", "-C", r, "pkg/deep/x.py")
    run(capsys, "undo", "-C", r)
    assert sorted(p.name for p in (tree / "pkg").iterdir()) == ["a.py", "b.py"]
