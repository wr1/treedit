"""Math spans in the Markdown preview: protected before marked, then rendered by KaTeX."""

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


def page() -> str:
    return (resources.files("treedit") / "page.html").read_text("utf-8")


def run(expr: str, lib: str) -> object:
    prog = lib + f"\nprocess.stdout.write(JSON.stringify({expr}));"
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


def ranges(src: str):
    lib = js_function(page(), "mathRanges")
    return run(f"mathRanges({json.dumps(src)})", lib)


def test_inline_display_and_latex_delimiters():
    spans = ranges("a $M_y$ b $$x^2$$ c \\(y\\) d \\[z\\]")
    assert [(s["tex"], s["display"]) for s in spans] == [
        ("M_y", False),
        ("x^2", True),
        ("y", False),
        ("z", True),
    ]


def test_display_math_may_span_lines_but_inline_math_may_not():
    assert [s["display"] for s in ranges("$$\n\\begin{aligned}\na &= b\\\\\n\\end{aligned}\n$$")] == [True]
    assert ranges("$a\nb$") == []


def test_currency_and_escapes_stay_prose():
    assert ranges("it costs $5 and $10 today") == []
    assert ranges(r"a literal \$x\$ sign") == []


def test_code_examples_keep_their_dollars():
    src = "`$a$` and ``$b$``\n\n```md\n| $c$ |\n| --- |\n```\n\n$x$"
    assert [s["tex"] for s in ranges(src)] == ["x"]


def test_tex_backslashes_survive_protection():
    src = r"| Case | Load |" + "\n| --- | --- |\n" + r"| $U12\_ETM$ | $13.10\%$ |"
    lib = js_function(page(), "mathRanges") + "\n" + js_function(page(), "protectMath")
    out = run(f"protectMath({json.dumps(src)})", lib)
    assert out["math"] == [
        {"tex": r"U12\_ETM", "raw": r"$U12\_ETM$", "display": False},
        {"tex": r"13.10\%", "raw": r"$13.10\%$", "display": False},
    ]
    assert "\ue0000\ue001" in out["src"] and "$" not in out["src"]


def test_source_offsets_follow_the_original_text():
    src = "# Title\n\nA $x$ here.\n\n| $a$ | b |\n| --- | --- |\n| 1 | 2 |\n"
    lib = (
        js_function(page(), "mathRanges")
        + "\n"
        + js_function(page(), "protectMath")
        + "\n"
        + js_function(page(), "mdTokenOffsets")
        + "\n"
        + js_function(page(), "mdRenderer")
    )
    prog = (
        f"globalThis.marked = require({json.dumps(str(resources.files('treedit') / 'vendor' / 'marked.js'))});\n"
        + lib
        + f"\nconst src = {json.dumps(src)}, pm = protectMath(src);\n"
        + "const tokens = marked.lexer(pm.src, { gfm: true });\n"
        + "const found = mdTokenOffsets(tokens, pm.src);\n"
        + "const offs = { get: t => { const at = found.get(t); return at == null ? null : pm.mapOffset(at); } };\n"
        + "process.stdout.write(JSON.stringify({"
        + " html: marked.parser(tokens, { gfm: true, renderer: mdRenderer(offs) }),"
        + " heading: pm.mapOffset(pm.src.indexOf('A ')),"
        + " table: pm.mapOffset(pm.src.indexOf('| ')) }));"
    )
    out = json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)
    assert '<h1 data-src="0">Title</h1>' in out["html"]
    assert f'<div class="md-table" data-src="{src.index("| $a$")}">' in out["html"]
    assert out["heading"] == src.index("A $x$")
    assert out["table"] == src.index("| $a$")
