"""Which tree files offer the Make menu (page.html, run in node)."""

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
def is_makefile():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    lib = js_function(src, "isMakefile")
    return lambda path: json.loads(
        subprocess.run(
            [NODE, "-e", lib + f"\nprocess.stdout.write(JSON.stringify(isMakefile({json.dumps(path)})));"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )


def test_makefile_names(is_makefile):
    assert is_makefile("Makefile") and is_makefile("pkg/GNUmakefile")
    assert is_makefile("build.mk") and is_makefile("a/b.make")
    assert not is_makefile("Makefile.am") and not is_makefile("README.md")
