"""The New box: several paths, one per line (page.html, run in node)."""

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


@pytest.fixture(scope="module")
def page():
    return (resources.files("treedit") / "page.html").read_text("utf-8")


@pytest.fixture(scope="module")
def lib(page):
    return js_function(page, "newPaths")


def names(lib: str, text: str):
    prog = lib + f"\nprocess.stdout.write(JSON.stringify(newPaths({json.dumps(text)})));"
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


def test_one_path_per_line(lib):
    assert names(lib, "a.txt\npkg/b.py\ndocs/") == ["a.txt", "pkg/b.py", "docs/"]


def test_commas_blanks_and_surrounding_slashes(lib):
    assert names(lib, " a.txt , pkg/b.py \n\n /x/ ") == ["a.txt", "pkg/b.py", "x/"]


def test_duplicates_keep_the_first(lib):
    assert names(lib, "a.txt\na.txt\nb.md") == ["a.txt", "b.md"]


def test_empty_box_makes_nothing(lib):
    assert names(lib, "  \n , \n") == []


def test_creation_has_no_second_dialog(page):
    body = js_function(page, "newAtDepth")
    assert "putModal" not in body and "dry_run" not in body
    assert "openModal('New'" in body
    assert "lastDefinedFile(paths, r.entries)" in body
    assert "made[0].kind === 'file'" not in body


def defined_file(page, paths, entries):
    fn = js_function(page, "lastDefinedFile")
    prog = fn + f"\nprocess.stdout.write(JSON.stringify(lastDefinedFile({json.dumps(paths)}, {json.dumps(entries)})));"
    raw = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout
    return json.loads(raw)


def test_done_opens_the_last_defined_file(page):
    entries = [
        {"action": "created", "kind": "dir", "path": "notes"},
        {"action": "created", "kind": "file", "path": "notes/todo.md"},
        {"action": "created", "kind": "dir", "path": "docs"},
        {"action": "created", "kind": "file", "path": "docs/guide.md"},
        {"action": "created", "kind": "dir", "path": "assets"},
        {"action": "created", "kind": "dir", "path": "assets/img"},
        {"action": "created", "kind": "dir", "path": "src"},
        {"action": "created", "kind": "dir", "path": "src/pkg"},
    ]
    paths = ["notes/todo.md", "docs/guide.md", "assets/img/", "src/pkg"]
    assert defined_file(page, paths, entries) == "docs/guide.md"


def test_a_file_under_a_new_folder_is_the_file(page):
    entries = [
        {"action": "created", "kind": "dir", "path": "notes"},
        {"action": "created", "kind": "file", "path": "notes/todo.md"},
    ]
    assert defined_file(page, ["notes/todo.md"], entries) == "notes/todo.md"


def test_folders_only_opens_no_file(page):
    entries = [
        {"action": "created", "kind": "dir", "path": "docs"},
        {"action": "created", "kind": "dir", "path": "v1.0"},
        {"action": "created", "kind": "dir", "path": "src/pkg"},
    ]
    assert defined_file(page, ["docs/", "v1.0/", "src/pkg"], entries) is None
