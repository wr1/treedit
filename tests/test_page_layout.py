"""Pane widths: the editor stays the wide column (page.html, run in node)."""

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
def panes():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    lib = "\n".join(js_function(src, n) for n in ("layoutPanes", "preferredPanes"))

    def call(avail, want_tree, want_term, term_on):
        prog = lib + (
            "\nprocess.stdout.write(JSON.stringify(preferredPanes("
            f"{avail}, {json.dumps(want_tree)}, {json.dumps(want_term)}, {str(term_on).lower()})));"
        )
        return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)

    return call


def test_saved_widths_on_a_short_window_give_the_editor_the_wide_column(panes):
    # The window used to open at ~1400px with a saved agent pane near 830px, leaving the editor a sliver.
    lay = panes(1359, 410, 829, True)
    assert lay["editor"] >= lay["tree"]
    assert lay["editor"] >= lay["term"]
    assert lay["editor"] >= round(1359 * 0.46)
    assert lay["tree"] + lay["term"] + lay["editor"] == 1359


def test_saved_widths_fit_on_a_maximized_screen(panes):
    lay = panes(2550, 410, 829, True)
    assert lay == {"tree": 410, "term": 829, "editor": 2550 - 410 - 829}


def test_fresh_window_keeps_the_editor_widest(panes):
    for avail in (1359, 1900, 2550):
        lay = panes(avail, None, None, True)
        assert lay["editor"] >= lay["tree"]
        assert lay["editor"] >= lay["term"]
        assert lay["editor"] >= round(avail * 0.46)
        assert lay["tree"] + lay["term"] + lay["editor"] == avail
        assert lay["tree"] <= 460
        assert lay["term"] <= 720


def test_hidden_agent_pane_leaves_its_width_to_the_editor(panes):
    lay = panes(1359, 410, 829, False)
    assert lay["term"] == 0
    assert lay["editor"] >= lay["tree"]
    assert lay["tree"] + lay["editor"] == 1359
