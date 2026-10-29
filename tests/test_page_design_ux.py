"""Design viewport and keyboard regressions, executed against the page functions."""

import json
import subprocess
from importlib import resources

from test_page_design import NODE, js_function, pytestmark as pytestmark


def run(body):
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    funcs = "\n".join(js_function(src, n) for n in ("dzFit", "dzZoom", "dzCycle", "dzEnsureVisible"))
    setup = """
const DZ = {zoom: 1, ox: 0, oy: 0, pos: {}, active: null};
const canvas = {clientWidth: 600, clientHeight: 400};
const $ = () => canvas;
const dzRender = () => {}, dzRevealNode = () => {};
const dzExtent = () => [30, 15, 260, 200];
"""
    result = subprocess.run([NODE, "-e", setup + funcs + "\n" + body], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_layout_leaves_room_for_tree_overlays():
    pos = run("console.log(JSON.stringify(dzFit({A:[0,0], B:[90,60], C:[90,100]})));")
    assert pos["B"][1] - pos["A"][1] >= 239
    assert pos["C"][1] - pos["B"][1] >= 239


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
