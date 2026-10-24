"""Source offsets on rendered Markdown blocks, so the preview can follow the caret."""

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


def test_blocks_carry_their_source_offset():
    page = (resources.files("treedit") / "page.html").read_text("utf-8")
    vendor = resources.files("treedit") / "vendor" / "marked.js"
    lib = js_function(page, "mdTokenOffsets") + "\n" + js_function(page, "mdRenderer")
    src = "# A\n\npara\n\n- x\n  - y\n\nend\n"
    prog = (
        f"globalThis.marked = require({json.dumps(str(vendor))});\n"
        + lib
        + f"\nconst src = {json.dumps(src)};\n"
        + "const tokens = marked.lexer(src);\n"
        + "process.stdout.write(marked.parser(tokens, { renderer: mdRenderer(mdTokenOffsets(tokens, src)) }));"
    )
    html = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout
    assert '<h1 data-src="0">A</h1>' in html
    assert '<p data-src="5">para</p>' in html
    assert '<li data-src="11">x' in html
    assert '<li data-src="17">y</li>' in html  # a nested item has its own offset
    assert '<p data-src="22">end</p>' in html
