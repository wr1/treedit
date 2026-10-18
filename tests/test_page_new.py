"""Names a multi-file create reads from the box (page.html, run in node)."""

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
    return js_function(src, "parseNames")


def names(lib: str, text: str):
    prog = lib + f"\nprocess.stdout.write(JSON.stringify(parseNames({json.dumps(text)})));"
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


def test_one_name_per_line(lib):
    assert names(lib, "a.txt\npkg/b.py") == ["a.txt", "pkg/b.py"]


def test_commas_blanks_and_surrounding_slashes(lib):
    assert names(lib, " a.txt , pkg/b.py \n\n /x/ ") == ["a.txt", "pkg/b.py", "x"]


def test_duplicates_keep_the_first(lib):
    assert names(lib, "a.txt\na.txt\npkg/a.txt") == ["a.txt", "pkg/a.txt"]


def test_empty_box_makes_nothing(lib):
    assert names(lib, "  \n , ") == []
