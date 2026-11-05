"""Design viewport and keyboard regressions, executed against page.html's real Design-mode code."""

import json
import subprocess

from design_layout_eval import HERE, design_md, page_code
from test_page_design import NODE, pytestmark as pytestmark

DOOR = (HERE / "fixtures" / "door-design.md").read_text("utf-8")  # frozen: examples/ is the user's to edit


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


# Minder's mind-map keys (src/Shortcuts.vala; /workspace notes: minder-keys.md) on the Design canvas --------------------

MK = """
const press = (k, m = {}) => dzKey({ key: k, ...m, target: {}, preventDefault() {}, stopPropagation() {} });
const type = (text, k, m = {}) => dzEditKey({ key: k, ...m, preventDefault() {}, stopPropagation() {} }, DZ.edit, { value: text });
const lines = () => editor.value.split('\\n');
const at = t => lines().findIndex(l => l.trim() === '- ' + t);
const cur = () => DZ.cur ? lines()[DZ.cur.line] : null;
const pick = t => dzSelectItem('Closed', at(t));
const diff = (a, b) => { const A = a.split('\\n'), B = b.split('\\n'); return { added: B.filter(l => !A.includes(l)), removed: A.filter(l => !B.includes(l)) }; };
DZ.active = 'Closed';
const md0 = editor.value;
const out = {};
const show = () => console.log(JSON.stringify(out));
"""


def mk(body):
    return run(DOOR, MK + body + "\nshow();")


def test_tab_on_a_state_adds_its_last_top_item_typed_in_place():
    r = mk(
        "press('Tab'); out.slot = DZ.edit; type('closes in 5 s', 'Escape'); out.cur = cur(); out.d = diff(md0, editor.value); out.after = lines()[at('closes in 5 s') - 1];"
    )
    assert r["slot"] == {"id": "Closed", "line": None, "value": ""}
    assert r["d"] == {"added": ["- closes in 5 s"], "removed": []}
    assert r["after"] == "- shows: green LED" and r["cur"] == "- closes in 5 s"


def test_enter_on_a_state_adds_a_state_and_shift_enter_one_linked_from_it():
    r = mk("""
const n0 = DZ.model.nodes.length, e0 = DZ.model.edges.length;
press('Enter'); out.enter = [DZ.model.nodes.length - n0, DZ.model.edges.length - e0, !!DZ.rename];
DZ.rename = null; DZ.active = 'Closed'; press('Enter', { shiftKey: true });
out.shift = [DZ.model.nodes.length - n0, DZ.model.edges.filter(e => e.from === 'Closed').length];""")
    assert r["enter"] == [1, 0, True], "Minder add_root_node: a loose state, named in place"
    assert r["shift"] == [2, 3], "Minder add_connected_node: linked from the state"


def test_arrows_follow_the_mind_map_right_child_left_parent_up_down_siblings():
    r = mk("""
const seq = [];
for (const k of ['ArrowRight', 'ArrowDown', 'ArrowRight', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']) { press(k); seq.push(cur() || DZ.active); }
out.seq = seq; out.same = editor.value === md0;""")
    assert r["seq"] == [
        "- entry: motor off",  # Right of the state: its first top item
        "- accepts",
        "  - open (if not blocked)",
        "  - lock",
        "  - lock",  # nothing below: Minder's Down does not wrap
        "- accepts",
        "- entry: motor off",
        "- accepts",
        "Closed",  # Left of a top item is its state
        "- accepts",  # Right goes back to the last selected child (Minder last_selected_child)
    ]
    assert r["same"], "navigation never touches the Markdown"


def test_vim_letters_and_page_keys_navigate_like_minder():
    r = mk("""
const seq = [];
for (const k of ['ArrowRight', 'j', 'c', 'j', 'k', 'a', 'n', 'n', 'n', 'p', 'PageDown', 'PageUp', 'h', 'm']) { press(k); seq.push(cur() || DZ.active); }
out.seq = seq;""")
    assert r["seq"] == [
        "- entry: motor off",
        "- accepts",
        "  - open (if not blocked)",
        "  - lock",
        "  - open (if not blocked)",
        "- accepts",
        "- shows: green LED",
        "- entry: motor off",  # n/p wrap (Minder sibling_node(wrap))
        "- accepts",
        "- entry: motor off",
        "- accepts",
        "- entry: motor off",
        "Closed",
        "Closed",
    ]


def test_tab_on_an_item_adds_a_child_enter_a_sibling_after_shift_enter_one_before():
    r = mk("""
pick('shows: green LED'); press('Tab'); type('red when locked', 'Escape'); out.child = [lines()[at('shows: green LED') + 1], cur()];
let md = editor.value; pick('entry: motor off'); press('Enter'); type('x', 'Escape'); out.after = [lines()[at('entry: motor off') + 1], diff(md, editor.value)];
md = editor.value; pick('accepts'); press('Enter', { shiftKey: true }); type('y', 'Escape'); out.before = [lines()[at('accepts') - 1], diff(md, editor.value)];""")
    assert r["child"] == ["  - red when locked", "  - red when locked"]
    assert r["after"] == ["- x", {"added": ["- x"], "removed": []}]
    assert r["before"] == ["- y", {"added": ["- y"], "removed": []}]


def test_shift_tab_on_an_item_adds_a_parent_above_it():
    r = mk(
        "pick('lock'); press('Tab', { shiftKey: true }); type('guarded', 'Escape'); out.l = lines().slice(at('accepts'), at('accepts') + 4); out.cur = cur();"
    )
    assert r["l"] == ["- accepts", "  - open (if not blocked)", "  - guarded", "    - lock"]
    assert r["cur"] == "  - guarded"


def test_typing_enter_tab_and_esc_build_a_branch_and_esc_keeps_the_text():
    r = mk("""
press('Tab'); type('a', 'Enter'); type('b', 'Tab'); type('c', 'Escape');
out.tail = lines().slice(at('shows: green LED') + 1, at('shows: green LED') + 4); out.cur = cur(); out.edit = DZ.edit;
pick('entry: motor off'); press('e'); out.editing = DZ.edit && DZ.edit.line === at('entry: motor off'); type('entry: motor on', 'Escape');
out.kept = at('entry: motor on') > 0 && at('entry: motor off') < 0;""")
    assert r["tail"] == ["- a", "- b", "  - c"]
    assert r["cur"] == "  - c" and r["edit"] is None
    assert r["editing"] and r["kept"], "Esc ends the edit and keeps the text (Minder edit_escape)"


def test_empty_new_slot_tab_moves_it_under_the_item_above_and_enter_closes_it():
    r = mk("""
press('Tab'); type('a', 'Enter'); type('', 'Tab'); out.slot = DZ.edit && DZ.edit.parent === at('a'); type('b', 'Enter'); type('', 'Enter');
out.tail = lines().slice(at('a'), at('a') + 3); out.cur = cur(); out.edit = DZ.edit;""")
    assert r["slot"]
    assert r["tail"][:2] == ["- a", "  - b"] and r["tail"][2] != "- "
    assert r["cur"] == "  - b" and r["edit"] is None, "an empty slot closes and selects the item it hung from"


def test_delete_removes_the_subtree_and_selects_next_sibling_shift_delete_keeps_children():
    r = mk("""
pick('accepts'); press('Delete'); out.del = [md0.split('\\n').length - lines().length, lines()[at('entry: motor off') + 1], cur()];
open(md0); DZ.active = 'Closed'; pick('shows: green LED'); press('Backspace'); out.last = cur();
open(md0); DZ.active = 'Closed'; pick('accepts'); press('Delete', { shiftKey: true }); out.only = [lines().slice(at('entry: motor off') + 1, at('entry: motor off') + 4), cur()];
open(md0); DZ.active = 'Closed'; pick('entry: motor off'); press('Delete'); press('Delete'); press('Delete'); out.parent = [cur(), DZ.active];""")
    assert r["del"] == [3, "- shows: green LED", "- shows: green LED"]
    assert r["last"] == "- accepts", "no next sibling: the previous one (Minder node_remove)"
    assert r["only"] == [["- open (if not blocked)", "- lock", "- shows: green LED"], "- open (if not blocked)"]
    assert r["parent"] == [None, "Closed"], "last item gone: back to the state"


def test_alt_arrows_reorder_and_move_items_between_levels():
    r = mk("""
pick('lock'); press('ArrowUp', { altKey: true }); out.up = [lines().slice(at('accepts') + 1, at('accepts') + 3), cur()];
press('ArrowDown', { altKey: true }); out.down = lines().slice(at('accepts') + 1, at('accepts') + 3);
press('ArrowLeft', { altKey: true }); out.left = [lines().slice(at('entry: motor off') + 1, at('entry: motor off') + 4), cur()];
open(md0); DZ.active = 'Closed'; pick('accepts'); press('ArrowRight', { altKey: true }); out.right = [lines().slice(at('entry: motor off') + 1, at('entry: motor off') + 4), cur()];""")
    assert r["up"] == [["  - lock", "  - open (if not blocked)"], "  - lock"]
    assert r["down"] == ["  - open (if not blocked)", "  - lock"]
    assert r["left"] == [["- lock", "- accepts", "  - open (if not blocked)"], "- lock"], (
        "Minder make_parent_sibling: before the parent"
    )
    assert r["right"] == [["- open (if not blocked)", "- lock", "- accepts"], "- accepts"], (
        "Minder make_children_siblings"
    )


def test_f_folds_the_branch_or_map_and_shift_f_folds_deep():
    r = mk("""
pick('accepts'); press('f'); out.branch = [...DZ.folded].filter(k => k !== 'Closed').length; out.cur = cur(); press('f'); out.open = [...DZ.folded].length;
press('m'); press('f'); out.map = DZ.folded.has('Closed'); press('f');
press('F', { shiftKey: true }); out.deep = [DZ.folded.has('Closed'), [...DZ.folded].length > 1];
out.same = editor.value === md0;""")
    assert r["branch"] == 1 and r["cur"] == "- accepts" and r["open"] == 0
    assert r["map"] is True
    assert r["deep"] == [True, True]
    assert r["same"], "folding is layout state, not Markdown"


def test_esc_on_an_item_returns_to_the_state_and_shift_c_centres_the_item():
    r = mk("""
pick('lock'); const z = [DZ.ox, DZ.oy]; press('C', { shiftKey: true }); out.moved = DZ.ox !== z[0] || DZ.oy !== z[1];
press('Escape'); out.back = [DZ.cur, DZ.active];""")
    assert r["moved"]
    assert r["back"] == [None, "Closed"]


def test_zoom_keys_plain_and_ctrl_forms():
    r = mk("""
press('1'); const fit = DZ.zoom; press('0'); out.actual = DZ.zoom; press('='); out.inn = DZ.zoom > 1; press('-'); press('-'); out.outt = DZ.zoom < 1;
press('1', { ctrlKey: true }); out.fit = DZ.zoom === fit; press('0', { ctrlKey: true }); out.cactual = DZ.zoom;
pick('lock'); const o = [DZ.ox, DZ.oy]; press('2'); out.sel = DZ.ox !== o[0] || DZ.oy !== o[1];
press('?', { ctrlKey: true }); out.help = DZ.help;""")
    assert r == {"actual": 1, "inn": True, "outt": True, "fit": True, "cactual": 1, "sel": True, "help": True}


def test_ctrl_z_and_ctrl_shift_z_are_undo_and_redo():
    r = run(
        DOOR,
        "const k = (key, m) => undoKey({ key, ctrlKey: true, ...m });"
        "console.log(JSON.stringify([k('z'), k('Z', { shiftKey: true })]));",
    )
    assert r == [-1, 1]
