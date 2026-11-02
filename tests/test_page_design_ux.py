"""Design viewport and keyboard regressions, executed against page.html's real Design-mode code."""

import json
import subprocess

from design_layout_eval import HERE, design_md, page_code
from test_page_design import NODE, pytestmark as pytestmark

DOOR = (HERE.parent / "examples" / "door-design.md").read_text("utf-8")


def run(md, body, w=600, h=400):
    prog = "\n".join(
        [
            f"const CANVAS = {{W: {w}, H: {h}}};",
            (HERE / "layout_metrics.js").read_text("utf-8"),
            (HERE / "design_layout_harness.js").read_text("utf-8"),
            page_code(),
            f"open({json.dumps(md)});",
            body,
        ]
    )
    result = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_layout_leaves_room_for_mind_maps():
    blocks = run(DOOR, "console.log(JSON.stringify(Object.values(boxes())));")
    for i, a in enumerate(blocks):
        for b in blocks[i + 1 :]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (a, b)


def test_zoom_keeps_point_under_pointer():
    state = run(DOOR, "DZ.ox=20; DZ.oy=30; DZ.zoom=1; dzZoom(2, 100, 150); console.log(JSON.stringify(DZ));")
    assert state["zoom"] == 2
    assert 80 * state["zoom"] + state["ox"] == 100
    assert 120 * state["zoom"] + state["oy"] == 150


def test_cycle_reaches_disconnected_nodes_and_wraps():
    md = design_md("Loose", [("A", "B")], {}).replace("    A --> B\n", "    A --> B\n    Loose\n")
    result = run(
        md,
        """
if (!DZ.model.nodes.some(n => n.id === 'Loose')) throw new Error('no Loose node: ' + JSON.stringify(DZ.model.nodes));
DZ.active='B'; dzCycle(1); const first=DZ.active; dzCycle(1); const second=DZ.active; dzCycle(-1);
console.log(JSON.stringify([first, second, DZ.active]));
""",
    )
    assert result == ["Loose", "A", "Loose"]


def test_keyboard_selection_pans_just_enough_to_show_an_offscreen_node():
    md = design_md("Far", [("A", "B")], {})
    state = run(
        md,
        """
DZ.pos.A=[2000,3000]; dzRender(); DZ.active='A'; dzSee('A');
console.log(JSON.stringify({box: scene().nodes.A, ox: DZ.ox, oy: DZ.oy, zoom: DZ.zoom}));
""",
    )
    _, _, right, bottom = state["box"]
    assert state["zoom"] == 1
    assert (
        right + state["ox"] == 600 - 32 and bottom + state["oy"] == 400 - 32
    )  # Minder's see(): the node just inside, a pad off the edge


def test_return_edges_and_self_loop_have_separate_labels():
    md = design_md("Labels", [], {}).replace(
        "stateDiagram-v2\n", "stateDiagram-v2\n    A --> B : forward\n    B --> A : return\n    A --> A : retry\n"
    )
    labels = run(
        md,
        """
const out = [], walk = e => { if ((e.attrs && e.attrs.class === 'dz-elabel') || e.className === 'dz-elabel') out.push({text: e.textContent, x: e.attrs.x, y: e.attrs.y}); (e.children || []).forEach(walk); };
Object.values(ELS).forEach(walk);
console.log(JSON.stringify(out));
""",
    )
    assert sorted(label["text"] for label in labels) == ["forward", "retry", "return"]
    assert len({(label["x"], label["y"]) for label in labels}) == 3


KEY = "const press = k => dzKey({key: k, target: {}, preventDefault() {}, stopPropagation() {}});"


def test_question_mark_toggles_the_key_list_and_esc_closes_it_before_cancelling_a_link():
    result = run(
        DOOR,
        KEY
        + """
const seen = [DZ.help]; press('?'); seen.push(DZ.help); press('?'); seen.push(DZ.help);
DZ.active = 'Closed'; press('l'); press('?'); press('Escape'); seen.push(DZ.help, DZ.link); press('Escape'); seen.push(DZ.link);
console.log(JSON.stringify(seen));
""",
    )
    assert result == [False, True, False, False, True, False]


def test_key_list_is_a_corner_popover_not_a_bar_under_the_canvas():
    html = (HERE.parent / "src" / "treedit" / "page.html").read_text("utf-8")
    view = html[html.index('<div id="designview"') :]
    view = view[: view.index("</div></div></div>")]
    assert view.index('<div id="dz-canvas"') < view.index('<div id="dz-help">'), "help follows the canvas"
    assert '<div id="dz-help"><div class="dz-keys"' in view, "the key list lives in the help popover"
    assert 'id="dz-help-btn"' in view
    css = html[: html.index("</style>")]
    assert "#dz-help .dz-keys{display:none" in css, "hidden until hover, focus or ?"
    assert "#dz-help:hover .dz-keys,#dz-help:focus-within .dz-keys,#dz-help.open .dz-keys{display:flex}" in css
    assert "onmousedown = e => e.preventDefault()" in html, "clicking ? keeps focus on the canvas or name box"
