import json
import subprocess

import pytest

from conftest import git
from treedit.cli import _ws, merge_notes_log_text, merge_notes_text, sync_info, sync_repo


def clone(src, dst):
    subprocess.run(["git", "clone", "-q", str(src), str(dst)], check=True, capture_output=True)
    git(dst, "config", "user.email", "test@example.com")
    git(dst, "config", "user.name", "test")
    return dst


def notes(**kw):
    return json.dumps({"notes": kw.get("notes", {}), "feedback": kw.get("feedback", [])}, ensure_ascii=False)


@pytest.fixture
def pair(tmp_path):
    """A bare remote, the user's checkout A, and the other side's checkout B (both on main)."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    a = tmp_path / "a"
    subprocess.run(["git", "init", "-q", "-b", "main", str(a)], check=True, capture_output=True)
    git(a, "config", "user.email", "test@example.com")
    git(a, "config", "user.name", "test")
    (a / "README.md").write_text("one\n")
    _ws(str(a), "", [], False).add_feedback(["README.md"], "do the thing")
    git(a, "add", "-A")
    git(a, "commit", "-qm", "init")
    git(a, "remote", "add", "origin", str(bare))
    git(a, "push", "-q", "-u", "origin", "main")
    b = clone(bare, tmp_path / "b")
    return a, b


def test_sync_pulls_then_pushes(pair):
    a, b = pair
    (a / "README.md").write_text("one\ntwo\n")
    git(a, "commit", "-qam", "agent: two")
    git(a, "push", "-q")
    r = sync_repo(b)
    assert r["ok"] and r["incoming"] == 1 and r["pushed"] == 0
    assert (b / "README.md").read_text() == "one\ntwo\n"

    (b / "README.md").write_text("one\ntwo\nthree\n")
    r = sync_repo(b)
    assert r["ok"] and r["committed"] == 1 and r["pushed"] == 1
    git(a, "pull", "-q", "--rebase")
    assert (a / "README.md").read_text() == "one\ntwo\nthree\n"


def test_sync_outside_git(ws):
    assert sync_repo(ws.root)["error"] == "not a git repository"
    assert sync_info(ws.root)["state"] == "not-git"


def test_sync_skips_a_local_only_notes_repo(pair):
    a, _ = pair
    notes = a / "notes"
    notes.mkdir()
    subprocess.run(["git", "init", "-q", str(notes)], check=True, capture_output=True)
    git(notes, "config", "user.email", "test@example.com")
    git(notes, "config", "user.name", "test")
    (notes / "private.md").write_text("local only\n")
    git(notes, "add", "-A")
    git(notes, "commit", "-qm", "private notes")
    assert _ws(str(a), "", [], False).sync_repos() == [a.resolve()]


def test_sync_info_reports_drift(pair):
    a, b = pair
    assert sync_info(b)["state"] == "in-sync"
    (b / "README.md").write_text("dirty\n")
    info = sync_info(b)
    assert info["dirty"] == 1 and info["state"] == "dirty"
    git(b, "add", "-A")
    git(b, "commit", "-qm", "local")
    assert sync_info(b)["state"] == "ahead"
    (a / "README.md").write_text("remote\n")
    git(a, "commit", "-qam", "remote")
    git(a, "push", "-q")
    git(b, "fetch", "-q")
    info = sync_info(b)
    assert info["ahead"] == 1 and info["behind"] == 1 and info["state"] == "diverged"


def test_sync_reports_a_missing_remote(repo):
    r = sync_repo(repo)
    assert not r["ok"] and r["error"] == "no remote"


def test_sync_merges_feedback_from_both_sides(pair):
    a, b = pair
    _ws(str(a), "", [], False).update_feedback(1, reply="done on the other side", status="done")
    git(a, "commit", "-qam", "agent: reply to #1")
    git(a, "push", "-q")
    _ws(str(b), "", [], False).add_feedback(["README.md"], "a new request")
    r = sync_repo(b)
    assert r["ok"] and r["pushed"] == 1
    fb = _ws(str(b), "", [], False).read_feedback()
    assert [f["id"] for f in fb] == [1, 2]
    assert fb[0]["status"] == "done" and fb[0]["reply"] == "done on the other side"
    assert fb[1]["text"] == "a new request"
    git(a, "pull", "-q", "--rebase")  # the other side gets the new request next time
    assert [f["id"] for f in _ws(str(a), "", [], False).read_feedback()] == [1, 2]


def test_sync_merges_a_conflicting_notes_file(pair):
    a, b = pair
    _ws(str(a), "", [], False).add_feedback(["README.md"], "from the other side")
    git(a, "commit", "-qam", "user: feedback from the other side")
    git(a, "push", "-q")
    _ws(str(b), "", [], False).add_feedback(["README.md"], "from this side")
    r = sync_repo(b)
    assert r["ok"] and r["notes"] == 2 and r["pushed"] == 1  # the store and its change log
    fb = _ws(str(b), "", [], False).read_feedback()
    assert [f["id"] for f in fb] == [1, 2, 3]  # the local #2 stays; the remote one is renumbered
    assert [f["text"] for f in fb] == ["do the thing", "from this side", "from the other side"]


def test_sync_pushes_a_work_file_conflict(pair):
    a, b = pair
    (a / "README.md").write_text("their version\n")
    git(a, "commit", "-qam", "agent: theirs")
    git(a, "push", "-q")
    (b / "README.md").write_text("my version\n")
    r = sync_repo(b)
    assert r["ok"] and r["published"] == ["README.md"] and r["conflicts"] == []
    text = (b / "README.md").read_text()
    assert "<<<<<<<" in text and "my version" in text and "their version" in text
    assert git(b, "log", "-1", "--format=%s").startswith("user: sync conflict")
    assert git(b, "rev-parse", "HEAD") == git(b, "rev-parse", "origin/main")
    assert sync_info(b)["state"] == "conflict"


def test_sync_can_refuse_to_push_a_conflict(pair):
    a, b = pair
    (a / "README.md").write_text("their version\n")
    git(a, "commit", "-qam", "agent: theirs")
    git(a, "push", "-q")
    (b / "README.md").write_text("my version\n")
    r = sync_repo(b, publish=False)
    assert not r["ok"] and r["conflicts"] == ["README.md"] and r["published"] == []
    assert (b / "README.md").read_text() == "my version\n"
    assert git(b, "status", "--short").strip() == ""
    assert (
        subprocess.run(
            ["git", "-C", str(b), "rebase", "--show-current-patch"], capture_output=True, text=True
        ).returncode
        != 0
    )


def test_merge_notes_text_keeps_both_sides():
    base = notes(
        notes={"README.md": "standing note"},
        feedback=[{"id": 1, "text": "fix it", "status": "open", "reply": "", "updated": "2026-01-01T00:00:00+00:00"}],
    )
    ours = notes(
        notes={"README.md": "standing note", "new.md": "mine"},
        feedback=[
            {"id": 1, "text": "fix it", "status": "open", "reply": "", "updated": "2026-01-01T00:00:00+00:00"},
            {"id": 2, "text": "a request", "status": "open", "reply": "", "updated": "2026-01-02T00:00:00+00:00"},
        ],
    )
    theirs = notes(
        notes={"README.md": "their wording"},
        feedback=[
            {"id": 1, "text": "fix it", "status": "done", "reply": "fixed", "updated": "2026-01-03T00:00:00+00:00"}
        ],
    )
    out = json.loads(merge_notes_text(ours, theirs, base))
    assert out["notes"] == {"README.md": "their wording", "new.md": "mine"}
    assert [f["id"] for f in out["feedback"]] == [1, 2]
    assert out["feedback"][0]["status"] == "done" and out["feedback"][0]["reply"] == "fixed"
    assert out["feedback"][1]["text"] == "a request"


def test_merge_notes_text_renumbers_a_colliding_new_item():
    base = notes()
    ours = notes(feedback=[{"id": 1, "text": "mine", "status": "open", "reply": "", "updated": "1"}])
    theirs = notes(feedback=[{"id": 1, "text": "theirs", "status": "open", "reply": "", "updated": "2"}])
    got = json.loads(merge_notes_text(ours, theirs, base))["feedback"]
    assert [(f["id"], f["text"]) for f in got] == [(1, "mine"), (2, "theirs")]


def test_merge_notes_text_rejects_other_documents():
    assert merge_notes_text("not json", "{}", "{}") is None
    assert merge_notes_text('["a"]', "{}", "{}") is None


def event(seq, op, **kw):
    return {"seq": seq, "at": f"t{seq}", "who": "me", "op": op, **kw, "changes": []}


def log(*events):
    return "".join(json.dumps(e) + "\n" for e in events)


def test_merge_notes_log_text_keeps_both_histories():
    local = log(event(1, "annotation set"), event(2, "new"))
    remote = log(event(1, "annotation set"), event(2, "feedback reply"), event(3, "undo", undoes=2))
    got = [json.loads(ln) for ln in merge_notes_log_text(local, remote).splitlines()]
    assert [(e["seq"], e["op"]) for e in got] == [(1, "annotation set"), (2, "new"), (3, "feedback reply"), (4, "undo")]
    assert got[3]["undoes"] == 3  # the remote undo now points at its renumbered target


def test_merge_notes_log_text_rejects_other_files():
    assert merge_notes_log_text("not json", "") is None
