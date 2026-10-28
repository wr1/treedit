"""The roll queue's item list (page.html, run in node) and its default minimized state."""

import json
import shutil
import subprocess
from importlib import resources

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")


def js_function(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i : k + 1]
    raise ValueError(name)


def queue_items(state: dict, dirty: list) -> list:
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    prog = (
        f"const S = {json.dumps(state)};\n"
        f"function dirtyBuffers() {{ return new Map({json.dumps(dirty)}); }}\n"
        f"{js_function(src, 'queueItems')}\n"
        "process.stdout.write(JSON.stringify(queueItems()));"
    )
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


def test_new_items_since_the_last_roll_and_held_items():
    state = {
        "changes": {
            "a.md": {"at": 20, "by": "you"},
            "b.md": {"at": 5, "by": "you"},
            "c.md": {"at": 99, "by": "agent"},
        },
        "drafts": {"d.md": {"diff": "+x"}},
        "notes": {"n": "new note", "m": "same note"},
        "feedback": [
            {"id": 1, "status": "open", "paths": ["a.md"], "text": "why?"},
            {"id": 2, "status": "done", "paths": ["a.md"], "text": "done"},
            {"id": 3, "status": "open", "paths": ["a.md"], "text": "rolled"},
        ],
        "queue": {
            "at": 10,
            "notes": {"m": "same note", "n": "old note"},
            "feedback": ["3"],
            "held": [
                {"key": "note:held", "kind": "note", "path": "held.md", "text": "keep me"},
                {"key": "fb:9", "kind": "feedback", "id": 9, "path": "gone.md", "text": "answered elsewhere"},
            ],
        },
    }
    items = queue_items(state, [["e.md", {}], ["d.md", {}]])
    assert sorted(it["key"] for it in items) == [
        "draft:d.md",
        "draft:e.md",
        "edit:a.md",
        "fb:1",
        "note:held",
        "note:n",
    ]
    kinds = {it["key"]: it["kind"] for it in items}
    assert kinds["edit:a.md"] == "edit" and kinds["draft:d.md"] == "draft"
    assert kinds["note:n"] == "note" and kinds["fb:1"] == "feedback"
    feedback = next(it for it in items if it["kind"] == "feedback")
    assert feedback["id"] == 1 and feedback["lines"] is None


def test_queue_starts_minimized():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    assert '<div id="qbody" hidden>' in src
    assert 'id="qcount"' in src
    assert "queueOpen: load('queueopen', false)" in src
