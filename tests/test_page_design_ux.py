"""Design viewport and keyboard regressions, executed against the page functions."""

import json
import subprocess
from importlib import resources

from test_page_design import NODE, js_function, pytestmark as pytestmark


def run(body):
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    funcs = "\n".join(js_function(src, n) for n in ("dzFit", "dzFrame", "dzZoom", "dzCycle", "dzEnsureVisible"))
    setup = """
const DZ = {zoom: 1, ox: 0, oy: 0, pos: {}, active: null};
const canvas = {clientWidth: 600, clientHeight: 400};
const $ = () => canvas;
const dzRender = () => {}, dzRevealNode = () => {};
const dzExtent = () => [30, 15, 260, 200];
"""
    result = subprocess.run([NODE, "-e", setup + funcs + "\n" + body], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_design_help_does_not_change_height():
    """The key strip under the graph is one fixed line. A focus or link hint must not reflow it."""
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    assert ".dz-focus" not in src and "#dz-canvas:not(:focus)" not in src
    mark = ".dz-keys{flex:none;"
    rule = src[src.index(mark) : src.index("}", src.index(mark))]
    assert "flex-wrap:nowrap" in rule and "overflow-y:hidden" in rule


def test_layout_leaves_room_for_tree_overlays():
    """Wide tree boxes stay a gap apart. They may slide sideways; they must not be drawn on top of each other."""
    pos = run("console.log(JSON.stringify(dzFit({A:[0,0], B:[90,60], C:[90,100]})));")
    gap = 24
    for a, b in (("A", "B"), ("B", "C"), ("A", "C")):
        ax, ay = pos[a]
        bx, by = pos[b]
        ox = min(ax + 260, bx + 260) - max(ax - 30, bx - 30)
        oy = min(ay + 200, by + 200) - max(ay - 15, by - 15)
        assert ox + gap <= 2 or oy + gap <= 2, (a, b, ox, oy)


def test_fit_slides_aside_when_that_clears_a_wide_tree():
    """A wide tree that barely overlaps its neighbour slides sideways. It is not sent a full tree-height below."""
    pos = run("console.log(JSON.stringify(dzFit({A:[0,0], B:[250,0]})));")
    assert abs(pos["B"][1] - pos["A"][1]) < 40
    assert pos["B"][0] - pos["A"][0] > 250


def _framed(body):
    return run(
        "const boxes = " + body + """;
let L=Infinity,R=-Infinity,T=Infinity,B=-Infinity;
const f = dzFrame(boxes, 1400, 900, 1, true);
for (const [x,y,l,t,r,b] of boxes) {
  L=Math.min(L, x*f.spreadX - l); R=Math.max(R, x*f.spreadX + r);
  T=Math.min(T, y*f.spreadY - t); B=Math.max(B, y*f.spreadY + b);
}
console.log(JSON.stringify({...f, screenW:(R-L)*f.zoom, screenH:(B-T)*f.zoom}));
"""
    )


def test_frame_fills_the_slack_axis_of_a_tall_graph():
    framed = _framed("[[0,0,40,20,40,40],[200,200,40,20,40,40],[-100,400,40,20,40,40],[400,600,40,20,40,40],[150,800,40,20,40,40]]")
    assert framed["spreadX"] > 1.5
    assert framed["spreadY"] < 1.05
    assert framed["screenW"] > 1400 - 48 - 2
    assert framed["screenH"] > 900 - 48 - 2


def test_frame_leaves_a_full_graph_unstretched():
    framed = _framed("[[0,0,30,15,30,15],[800,0,30,15,30,15],[0,520,30,15,30,15],[800,520,30,15,30,15]]")
    assert framed["spreadX"] < 1.15
    assert framed["spreadY"] < 1.15


def test_frame_grows_a_graph_smaller_than_the_pane():
    framed = _framed("[[0,0,20,10,20,10],[80,0,20,10,20,10]]")
    assert framed["zoom"] > 1
    assert framed["zoom"] <= 2.5


def test_zoom_keeps_point_under_pointer():
    state = run("DZ.ox=20; DZ.oy=30; dzZoom(2, 100, 150); console.log(JSON.stringify(DZ));")
    assert state["zoom"] == 2
    assert 80 * state["zoom"] + state["ox"] == 100
    assert 120 * state["zoom"] + state["oy"] == 150


def test_cycle_reaches_disconnected_nodes_and_wraps():
    result = run("""
DZ.model={nodes:[{id:'A'},{id:'B'},{id:'Loose'}], edges:[]}; DZ.active='B';
dzCycle(1); const first=DZ.active; dzCycle(1); const second=DZ.active; dzCycle(-1);
console.log(JSON.stringify([first, second, DZ.active]));
""")
    assert result == ["Loose", "A", "Loose"]


def test_keyboard_selection_brings_offscreen_node_into_view():
    state = run("DZ.active='A'; DZ.pos.A=[2000,3000]; dzEnsureVisible(); console.log(JSON.stringify(DZ));")
    assert 2000 + state["ox"] == 300
    assert 3000 + state["oy"] == 200


def test_return_edges_and_self_loop_have_separate_labels():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    setup = r"""
const made=[];
function element(tag='div') { return {tag, attrs:{}, style:{}, clientWidth:600, clientHeight:400,
  setAttribute(k,v){this.attrs[k]=v}, append(){}, replaceChildren(){}, addEventListener(){}}; }
const elements={}; const $=key=>elements[key] ||= element();
const document={createElementNS(ns,tag){const e=element(tag); made.push(e); return e;}};
const SVGNS='svg', dzHalf=()=>[30,15];
const DZ={model:{nodes:[{id:'A'},{id:'B'}],trees:{},edges:[
  {from:'A',to:'B',label:'forward'}, {from:'B',to:'A',label:'return'}, {from:'A',to:'A',label:'retry'}]},
  pos:{A:[0,0],B:[200,0]},pinned:true,ox:0,oy:0,zoom:1,folded:new Set()};
"""
    body = """
dzRender(); console.log(JSON.stringify(made.filter(e=>e.attrs.class==='dz-elabel').map(e=>({text:e.textContent,...e.attrs}))));
"""
    result = subprocess.run(
        [NODE, "-e", setup + js_function(src, "dzRender") + body], capture_output=True, text=True, check=True
    )
    labels = json.loads(result.stdout)
    assert [label["text"] for label in labels] == ["forward", "return", "retry"]
    assert (labels[0]["x"], labels[0]["y"]) != (labels[1]["x"], labels[1]["y"])
