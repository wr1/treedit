"""Markdown tables render in their own scroll box with alignment intact (page.html, run in node)."""

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


def render(src: str) -> str:
    page = (resources.files("treedit") / "page.html").read_text("utf-8")
    vendor = resources.files("treedit") / "vendor" / "marked.js"
    lib = js_function(page, "mdTokenOffsets") + "\n" + js_function(page, "mdRenderer")
    prog = (
        f"globalThis.marked = require({json.dumps(str(vendor))});\n"
        + lib
        + f"\nconst src = {json.dumps(src)};\n"
        + "const tokens = marked.lexer(src, { gfm: true });\n"
        + "process.stdout.write(marked.parser(tokens,"
        + " { gfm: true, renderer: mdRenderer(mdTokenOffsets(tokens, src)) }));"
    )
    return subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout


def test_table_gets_a_scroll_box_with_its_source_offset():
    src = "intro\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    at = src.index("| a |")
    html = render(src)
    assert f'<div class="md-table" data-src="{at}"><table>' in html
    assert html.count('class="md-table"') == 1
    assert "</table>" in html and html.rstrip().endswith("</div>")


def test_column_alignment_is_preserved():
    src = "| l | c | r |\n| :-- | :-: | --: |\n| 1 | 2 | 3 |\n"
    html = render(src)
    assert '<th align="left">l</th>' in html
    assert '<th align="center">c</th>' in html
    assert '<th align="right">r</th>' in html
    assert '<td align="right">3</td>' in html


def test_wide_cells_keep_their_content_and_inline_markup():
    src = (
        "| Wind Case | Root $M_y$ Mean [MNm] |\n"
        "| :---- | ----: |\n"
        "| **U12_ETM** | $77.975$ |\n"
        "| $U12\\_ETM$ | `0.05` |\n"
    )
    html = render(src)
    assert "<strong>U12_ETM</strong>" in html
    assert '<td align="right">$77.975$</td>' in html
    assert "<code>0.05</code>" in html


def test_each_table_has_its_own_box_and_offset():
    src = "| a |\n| --- |\n| 1 |\n\ntext\n\n| b |\n| --- |\n| 2 |\n"
    html = render(src)
    first, second = src.index("| a |"), src.index("| b |")
    assert f'<div class="md-table" data-src="{first}">' in html
    assert f'<div class="md-table" data-src="{second}">' in html
    assert html.count('class="md-table"') == 2
