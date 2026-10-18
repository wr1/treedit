"""Which files a subtree copy includes, and how they are joined for the clipboard (page.html)."""

import json
import shutil
import subprocess
from importlib import resources

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")
FUNCS = ["copyRoots", "skillFiles", "textFiles", "dedupeFiles", "filesForCopy", "copyHeading", "joinClipboard"]


def js_function(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i : k + 1]
    raise ValueError(name)


@pytest.fixture(scope="module")
def lib():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    return "\n".join(js_function(src, n) for n in FUNCS)


def js(lib: str, fn: str, *args):
    prog = lib + f"\nprocess.stdout.write(JSON.stringify({fn}(...{json.dumps(list(args))})));"
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


PACK = {
    "type": "dir",
    "path": "pack",
    "name": "pack",
    "children": [
        {
            "type": "dir",
            "path": "pack/child",
            "name": "child",
            "children": [
                {"type": "file", "path": "pack/child/SKILL.md", "name": "SKILL.md", "kind": "text"},
                {"type": "file", "path": "pack/child/leaf.md", "name": "leaf.md", "kind": "text"},
            ],
        },
        {"type": "file", "path": "pack/SKILL.md", "name": "SKILL.md", "kind": "text"},
        {"type": "file", "path": "pack/README.md", "name": "README.md", "kind": "text"},
        {"type": "file", "path": "pack/img.png", "name": "img.png", "kind": "binary"},
    ],
}


def test_copy_roots_drop_nested_and_follow_tree_order(lib):
    assert js(lib, "copyRoots", ["a/b", "a", "c", ""], ["", "a", "c"]) == [""]
    assert js(lib, "copyRoots", ["a/b", "c", "a"], ["c", "a", "a/b"]) == ["c", "a"]
    assert js(lib, "copyRoots", ["b", "a"], ["a", "b"]) == ["a", "b"]
    assert js(lib, "copyRoots", ["ab", "a"], ["a", "ab"]) == ["a", "ab"]


def test_skill_subtree_is_parent_then_children_only(lib):
    plan = js(lib, "filesForCopy", [PACK])
    assert plan["kind"] == "skill"
    assert [f["path"] for f in plan["files"]] == ["pack/SKILL.md", "pack/child/SKILL.md"]


def test_overlapping_nodes_are_listed_once(lib):
    child = PACK["children"][0]
    plan = js(lib, "filesForCopy", [PACK, child])
    assert [f["path"] for f in plan["files"]] == ["pack/SKILL.md", "pack/child/SKILL.md"]


def test_text_files_when_the_subtree_has_no_skill(lib):
    node = {
        "type": "dir",
        "path": "pkg",
        "children": [
            {"type": "file", "path": "pkg/a.py", "name": "a.py", "kind": "text"},
            {
                "type": "dir",
                "path": "pkg/sub",
                "children": [{"type": "file", "path": "pkg/sub/c.py", "name": "c.py", "kind": "text"}],
            },
            {"type": "file", "path": "pkg/b.bin", "name": "b.bin", "kind": "binary"},
        ],
    }
    plan = js(lib, "filesForCopy", [node])
    assert plan["kind"] == "text"
    assert [f["path"] for f in plan["files"]] == ["pkg/a.py", "pkg/sub/c.py"]


def test_one_file_is_itself(lib):
    skill = {"type": "file", "path": "a/SKILL.md", "name": "SKILL.md", "kind": "text"}
    assert js(lib, "filesForCopy", [skill]) == {"kind": "skill", "files": [{"path": "a/SKILL.md", "name": "SKILL.md"}]}
    note = {"type": "file", "path": "README.md", "name": "README.md", "kind": "text"}
    assert js(lib, "filesForCopy", [note])["kind"] == "text"


def test_join_keeps_one_file_verbatim_and_heads_the_rest(lib):
    assert js(lib, "joinClipboard", [{"path": "a/SKILL.md", "text": "one\n"}]) == "one\n"
    assert js(lib, "joinClipboard", []) == ""
    assert (
        js(
            lib,
            "joinClipboard",
            [
                {"path": "a/SKILL.md", "text": "one\n"},
                {"path": "b/SKILL.md", "text": "two  \n"},
                {"path": "notes.md", "text": "n\n"},
            ],
        )
        == "## a\n\none\n\n## b\n\ntwo\n\n## notes.md\n\nn"
    )
