"""Design-mode layout criteria (docs/design-layout-eval.md) as tests.

Criteria the current layout meets are plain asserts; the ones it misses are strict xfails, so a fix
that meets one turns its test into an XPASS failure until the marker is removed.
"""

import pytest

from design_layout_eval import measure_all
from test_page_design import pytestmark as pytestmark

LEGIBLE_PX = 11  # proposed: the page's own smallest text (.dz-elabel, 11px)
MIN_GAP_PX = 12  # proposed: about one line of 12px text between boxes
WHITESPACE_MAX = 0.75  # proposed: at least a quarter of the drawing's bounding box is boxes
STILL_PX = 2  # proposed: existing nodes move at most this much on screen when nothing needs revealing
BRANCH_GAP = (8, 100)  # proposed: Minder's node_margin..branch_margin between parent and new child
EXCESS_PAN_PX = 20  # proposed: a pan goes at most this far past the minimal one that reveals the node


@pytest.fixture(scope="module")
def runs():
    data = measure_all()
    return [(f"{s} @ {c}", r) for s, per in data.items() for c, r in per.items()]


def misses(runs, bad):
    return [name for name, r in runs if bad(r)]


# met today ---------------------------------------------------------------------------------------


def test_layout_is_deterministic_and_saved_layout_reopens_unchanged(runs):
    assert not misses(runs, lambda r: not r["deterministic"] or r["reopenSavedMaxMove"] != 0)


def test_no_overlaps_at_open(runs):
    assert not misses(runs, lambda r: r["open"]["overlaps"])


def test_existing_nodes_keep_model_positions_on_insert_and_typing(runs):
    assert not misses(runs, lambda r: max(i["modelMaxMove"] for i in r["insert"]) or r["typed"]["modelMaxMove"])


def test_layout_button_is_idempotent(runs):
    assert not misses(runs, lambda r: r["layoutButton"]["secondPressMaxMove"])


def test_no_needless_pans_when_cycling(runs):
    assert not misses(runs, lambda r: r["cycle"]["needlessPans"] or r["cycle"]["nodeBoxOutOfView"])


# missed today ------------------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="fit-all zoom on open shrinks text below 11px (dzRender fitNext)")
def test_text_legible_at_default_zoom(runs):
    assert not misses(runs, lambda r: r["open"]["nodePx"] < LEGIBLE_PX or r["open"]["treePx"] < LEGIBLE_PX)


@pytest.mark.xfail(strict=True, reason="force layout (K=230) spreads nodes; fit-all shrinks the gaps")
def test_spacing_readable_and_compact(runs):
    assert not misses(
        runs, lambda r: r["open"]["minGapPx"] < MIN_GAP_PX or r["open"]["whitespaceRatio"] > WHITESPACE_MAX
    )


@pytest.mark.xfail(strict=True, reason="dzAddNode puts the node at +90,+60, inside the parent's tree overlay")
def test_new_node_does_not_overlap(runs):
    assert not misses(runs, lambda r: any(i["newOverlaps"] for i in r["insert"]) or r["afterInserts"]["overlaps"])


@pytest.mark.xfail(strict=True, reason="new nodes are not placed beside their parent at a branch gap")
def test_new_node_placed_beside_parent(runs):
    lo, hi = BRANCH_GAP
    ok = lambda g: lo <= g <= hi  # noqa: E731
    assert not misses(
        runs,
        lambda r: (
            not all(ok(i["gapToParentPx"]) and i["rightOfParent"] for i in r["insert"])
            or not ok(r["typed"]["gapToParentPx"])
        ),
    )


@pytest.mark.xfail(strict=True, reason="dzRender re-centres the unpinned view on every render")
def test_view_holds_still_on_edit(runs):
    def moved(r):
        ins = [max(i["screenMaxMoveOnAdd"], i["screenMaxMoveOnName"]) for i in r["insert"]]
        return max(ins + [r["treeItemScreenMaxMove"], r["typed"]["screenMaxMove"]]) > STILL_PX

    assert not misses(runs, moved)


@pytest.mark.xfail(strict=True, reason="dzEnsureVisible re-centres instead of the minimal pan")
def test_pans_are_minimal_and_new_nodes_in_view(runs):
    assert not misses(runs, lambda r: r["cycle"]["maxExcessPanPx"] > EXCESS_PAN_PX or not r["typed"]["inView"])


@pytest.mark.xfail(strict=True, reason="no Tab child / Enter sibling / Ctrl+1, Ctrl+0, Ctrl+2 / Shift+C keys")
def test_minder_default_keys(runs):
    keys = runs[0][1]["keys"]
    wanted = [
        "Tab (Minder: add child)",
        "Ctrl+1 (Minder: zoom to fit)",
        "Ctrl+2 (Minder: zoom to selected)",
        "Ctrl+0 (Minder: actual size)",
        "Shift+C (Minder: centre node)",
    ]
    assert [k for k in wanted if keys[k] == "nothing"] == []
    assert "adds node" in keys["Enter (Minder: add sibling)"]
