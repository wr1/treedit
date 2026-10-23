"""Markdown list indent/outdent helpers (page.html, run in node)."""

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
    return js_function(src, "mdIndentUnit") + "\n" + js_function(src, "mdIndentLines")


def run(lib: str, expr: str):
    prog = lib + f"\nprocess.stdout.write(JSON.stringify({expr}));"
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


def unit(lib: str, text: str):
    return run(lib, f"mdIndentUnit({json.dumps(text)})")


def outdent(lib: str, lines, unit_="  "):
    return run(lib, f"mdIndentLines({json.dumps(lines)}, true, {json.dumps(unit_)})")


def indent(lib: str, lines, unit_="  "):
    return run(lib, f"mdIndentLines({json.dumps(lines)}, false, {json.dumps(unit_)})")


def test_default_level_is_two_spaces(lib):
    assert unit(lib, "- a\n- b\n") == "  "


def test_level_follows_the_files_own_nesting(lib):
    assert unit(lib, "- a\n    - b\n") == "    "
    assert unit(lib, "- a\n  - b\n    - c\n") == "  "
    assert unit(lib, "- a\n\t- b\n") == "\t"


def test_outdent_removes_one_level(lib):
    assert outdent(lib, ["    - b"], "    ") == ["- b"]
    assert outdent(lib, ["  - b"], "  ") == ["- b"]
    assert outdent(lib, ["\t- b"], "\t") == ["- b"]


def test_outdent_a_top_level_bullet_removes_the_marker(lib):
    assert outdent(lib, ["- a"]) == ["a"]
    assert outdent(lib, ["* a"]) == ["a"]
    assert outdent(lib, ["1. a"]) == ["a"]
    assert outdent(lib, ["- [ ] a"]) == ["a"]
    assert outdent(lib, ["- [x] a"]) == ["a"]


def test_outdent_leaves_plain_prose_alone(lib):
    assert outdent(lib, ["plain"]) == ["plain"]
    assert outdent(lib, ["  prose"], "  ") == ["prose"]


def test_indent_adds_one_level(lib):
    assert indent(lib, ["- a"], "  ") == ["  - a"]
    assert indent(lib, ["- a", "", "- b"], "    ") == ["    - a", "", "    - b"]
