"""The editor's merge of your unsaved edits with a change on disk (page.html JavaScript, run in node)."""
import json
import shutil
import subprocess
from importlib import resources

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")
FUNCS = ["lineDiff", "unifiedDiff", "applyPatch", "lineHunks", "merge3"]


def js_function(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise ValueError(name)


@pytest.fixture(scope="module")
def page_lib():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    return "\n".join(js_function(src, n) for n in FUNCS)


@pytest.fixture(scope="module")
def merge3(page_lib):
    return lambda original, mine, theirs: js(page_lib, "merge3", original, mine, theirs)


def js(lib: str, fn: str, *args):
    prog = lib + f"\nprocess.stdout.write(JSON.stringify({fn}(...{json.dumps(list(args))})));"
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


BASE = "# Notes\n\n- a\n- b\n\n## Done\n\n- c\n"


def test_trivial(merge3):
    assert merge3(BASE, BASE, "x\n") == "x\n"
    assert merge3(BASE, "x\n", BASE) == "x\n"
    assert merge3(BASE, "x\n", "x\n") == "x\n"


def test_separate_edits_merge(merge3):
    mine = BASE.replace("- a", "- a, mine")
    theirs = BASE.replace("- c", "- c, theirs")
    assert merge3(BASE, mine, theirs) == BASE.replace("- a", "- a, mine").replace("- c", "- c, theirs")


@pytest.mark.parametrize("mine", [BASE + "\nNew paragraph.\n", "New first line\n" + BASE, BASE.replace("- b\n", "- b\n- new\n")])
def test_edit_already_on_disk_is_not_doubled(merge3, mine):
    assert merge3(BASE, mine, mine) == mine


def test_near_duplicate_conflicts_instead_of_doubling(merge3):
    mine = BASE + "\nNew paragraph with a typo teh.\n"
    theirs = BASE + "\nNew paragraph with a typo the.\n"
    assert merge3(BASE, mine, theirs) is None
    assert merge3(BASE, BASE.replace("- b\n", "- b\n- releese\n"), BASE.replace("- b\n", "- b\n- release\n")) is None


def test_same_line_changed_differently_conflicts(merge3):
    assert merge3(BASE, BASE.replace("- a", "- A"), BASE.replace("- a", "- aa")) is None


def test_same_edit_plus_separate_edit(merge3):
    both = BASE.replace("- a", "- A")
    assert merge3(BASE, both.replace("- c", "- C"), both) == both.replace("- c", "- C")


@pytest.mark.parametrize("original", ["", BASE])
def test_patch_applies_only_to_its_own_base(page_lib, original):
    mine = original + "# dealing with discrepancies\n\nProblem:\n- How to distinguish?\n"
    diff = js(page_lib, "unifiedDiff", original, mine)
    assert js(page_lib, "applyPatch", original, diff) == mine
    assert js(page_lib, "applyPatch", mine, diff) is None  # already on disk: never added a second time
