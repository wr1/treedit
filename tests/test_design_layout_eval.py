"""Design-mode layout criteria (docs/design-layout-eval.md) as tests.

Criteria the layout meets are plain asserts; the ones it misses are strict xfails, so a fix that meets
one turns its test into an XPASS failure until the marker is removed.
"""

import pytest

from design_layout_eval import measure_all
from test_page_design import pytestmark as pytestmark

LEGIBLE_PX = 11  # proposed: the page's own smallest text (.dz-elabel, 11px)
MIN_GAP_PX = 12  # proposed: about one line of 12px text between boxes
WHITESPACE_MAX = 0.75  # proposed: at least a quarter of the drawing's bounding box is boxes
STILL_PX = (
    2  # proposed: on an edit the camera moves at most this much past the minimal pan that reveals the edited node
)
BRANCH_GAP = (8, 100)  # proposed: Minder's node_margin..branch_margin between a new state's block and its source's
EXCESS_PAN_PX = 20  # proposed: a pan goes at most this far past the minimal one that reveals the node


@pytest.fixture(scope="module")
def runs():
    data = measure_all()
    return [(f"{s} @ {c}", r) for s, per in data.items() for c, r in per.items()]


def misses(runs, bad):
    return [name for name, r in runs if bad(r)]


# met ---------------------------------------------------------------------------------------------


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


def test_text_legible_at_default_zoom(runs):
    assert not misses(runs, lambda r: r["open"]["nodePx"] < LEGIBLE_PX or r["open"]["treePx"] < LEGIBLE_PX)


def test_blocks_readably_apart(runs):
    assert not misses(runs, lambda r: r["open"]["minGapPx"] < MIN_GAP_PX)


def test_new_node_does_not_overlap(runs):
    assert not misses(runs, lambda r: any(i["newOverlaps"] for i in r["insert"]) or r["afterInserts"]["overlaps"])


def test_view_holds_still_on_edit(runs):
    def excess(r):
        ins = [max(i["viewExcessOnAdd"], i["viewExcessOnName"]) for i in r["insert"]]
        return max(ins + [r["treeItemViewExcess"], r["typed"]["viewExcess"]]) > STILL_PX

    assert not misses(runs, excess)


def test_pans_are_minimal_and_new_nodes_in_view(runs):
    assert not misses(
        runs,
        lambda r: (
            r["cycle"]["maxExcessPanPx"] > EXCESS_PAN_PX
            or not r["typed"]["inView"]
            or not all(i["inView"] for i in r["insert"])
        ),
    )


def test_minder_view_keys(runs):
    keys = runs[0][1]["keys"]
    wanted = [
        "Ctrl+1 (Minder: zoom to fit)",
        "Ctrl+2 (Minder: zoom to selected)",
        "Ctrl+0 (Minder: actual size)",
        "Shift+C (Minder: centre node)",
    ]
    assert [k for k in wanted if keys[k] == "nothing"] == []


# missed ------------------------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="layered rows keep a channel of ROW + LANE per edge between ranks; small states leave 0.76-0.93 of the box empty",
)
def test_drawing_compact(runs):
    assert not misses(runs, lambda r: r["open"]["whitespaceRatio"] > WHITESPACE_MAX)


@pytest.mark.xfail(
    strict=True,
    reason="a new state goes 40px below its source's block, then steps right/down past what is in the way: up to ~214px",
)
def test_new_node_placed_next_to_source(runs):
    lo, hi = BRANCH_GAP
    ok = lambda g: lo <= g <= hi  # noqa: E731
    assert not misses(
        runs, lambda r: not all(ok(i["gapToParentPx"]) for i in r["insert"]) or not ok(r["typed"]["gapToParentPx"])
    )


@pytest.mark.xfail(strict=True, reason="Tab does nothing; Enter opens a mind-map item, not a sibling state")
def test_minder_edit_keys(runs):
    keys = runs[0][1]["keys"]
    assert keys["Tab (Minder: add child)"] != "nothing"
    assert "adds node" in keys["Enter (Minder: add sibling)"]


# two levels (docs/design-layout-eval.md, "State graph + mind maps"): (a) the state graph, (b) one mind map per state ----

REACH_MAX_PX = 640  # proposed: a mind map stays within about two Minder node widths (node_width 300) of its state
EDGE_LEN_RATIO = 3  # proposed: the longest downward state edge at most 3x the median one


def test_mind_map_reach_stays_near_its_state(runs):
    assert not misses(runs, lambda r: r["scene"]["mapReachPx"] > REACH_MAX_PX)


def test_unfold_moves_other_states_no_more_than_needed(runs):
    assert not misses(runs, lambda r: r["fold"]["overNeed"] > 0)


def test_state_edges_in_a_length_band_without_crossings(runs):
    s = lambda r: r["scene"]  # noqa: E731
    band = lambda r: s(r)["edgeLenForward"]  # noqa: E731
    assert not misses(runs, lambda r: s(r)["crossings"] or (band(r) and band(r)["ratio"] > EDGE_LEN_RATIO))


def test_mind_maps_clear_of_states_maps_and_edges(runs):
    s = lambda r: r["scene"]  # noqa: E731
    keys = ("stateOverlaps", "mapStateOverlaps", "mapMapOverlaps", "edgeMapHits", "edgeNodeHits")
    assert not misses(runs, lambda r: any(s(r)[k] for k in keys))


def test_mind_map_branches_evenly_spaced_beside_parent(runs):
    def bad(r):
        sib, br = r["scene"]["siblingGap"], r["scene"]["branchGap"]
        return not br or br["min"] < 16 or br["max"] - br["min"] > 2 or (sib and sib["std"] > 1)

    assert not misses(runs, bad)


def test_unfold_reserves_space(runs):
    assert not misses(runs, lambda r: r["fold"]["overlaps"] or r["fold"]["edgeHits"])


def test_fold_gives_space_back_and_keeps_camera(runs):
    assert not misses(runs, lambda r: r["fold"]["restoreMaxMove"] or r["fold"]["cameraChanges"])
