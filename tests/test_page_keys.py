"""Keyboard pane focus and tree stepping (page.html, run in node)."""

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
def lib():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    return "\n".join(js_function(src, n) for n in ("nextPane", "treeStep"))


def js(lib: str, fn: str, *args):
    prog = lib + f"\nprocess.stdout.write(JSON.stringify({fn}(...{json.dumps(list(args))})));"
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


def test_next_pane_wraps_at_both_ends(lib):
    assert js(lib, "nextPane", ["tree", "detail", "term"], "tree", 1) == "detail"
    assert js(lib, "nextPane", ["tree", "detail", "term"], "term", 1) == "tree"
    assert js(lib, "nextPane", ["tree", "detail", "term"], "tree", -1) == "term"
    assert js(lib, "nextPane", ["tree", "detail", "term"], "term", -1) == "detail"


def test_next_pane_starts_at_an_end_when_none_is_focused(lib):
    assert js(lib, "nextPane", ["tree", "detail"], None, 1) == "tree"
    assert js(lib, "nextPane", ["tree", "detail"], None, -1) == "detail"


def test_next_pane_skips_a_hidden_agent_pane(lib):
    assert js(lib, "nextPane", ["tree", "detail"], "detail", 1) == "tree"
    assert js(lib, "nextPane", ["tree", "detail"], "tree", -1) == "detail"
    assert js(lib, "nextPane", [], None, 1) is None


def test_tree_step_moves_and_stops_at_the_ends(lib):
    order = ["a", "b", "c"]
    assert js(lib, "treeStep", order, "a", 1) == "b"
    assert js(lib, "treeStep", order, "c", 1) == "c"
    assert js(lib, "treeStep", order, "a", -1) == "a"
    assert js(lib, "treeStep", order, "b", -1) == "a"


def test_tree_step_starts_from_an_end_when_nothing_is_selected(lib):
    order = ["a", "b", "c"]
    assert js(lib, "treeStep", order, None, 1) == "a"
    assert js(lib, "treeStep", order, "gone", 1) == "a"
    assert js(lib, "treeStep", order, None, -1) == "c"
    assert js(lib, "treeStep", [], None, 1) is None
