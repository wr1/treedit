"""Design-mode layout eval: measure spacing, legibility, stability, placement, framing and keys.

Runs page.html's real Design-mode code (designCore plus the dz* view functions) in node against a stub
DOM (tests/design_layout_harness.js), on treedit's own example and on synthetic design files.
Criteria, thresholds and the measured baseline: docs/design-layout-eval.md.

    uv run python tests/design_layout_eval.py            # table for every sample and canvas size
    uv run python tests/design_layout_eval.py --json     # the raw numbers
"""

import json
import re
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

NODE = shutil.which("node")
HERE = Path(__file__).resolve().parent
EXAMPLE = HERE.parent / "examples" / "door-design.md"
# the design canvas in a 1366x768 and a 1920x1080 browser window (measured with design_layout_browser.py)
CANVASES = {"1366x768 (637x264)": (637, 264), "1920x1080 (896x645)": (896, 645)}


def _between(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i : src.index(end, i)]


def _js_function(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i : k + 1]
    raise ValueError(name)


def page_code() -> str:
    """designCore, the DZ state and the whole Design-mode view block, verbatim from page.html."""
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    dz_state = re.search(r"^const DZ = \{.*\};$", src, re.M).group(0)
    view = _between(src, "const SVGNS = ", "$('#b-design').onclick")
    return "\n".join([_js_function(src, "designCore"), "const DC = designCore();", dz_state, view])


# ---------- samples: treedit's example plus synthetic design files ----------


def design_md(title: str, edges: list[tuple[str, str]], trees: dict[str, list[str]]) -> str:
    lines = ["---", f"name: {title}", "treedit: design", "---", f"# {title}", "", "```mermaid", "stateDiagram-v2"]
    lines += [f"    {a} --> {b}" for a, b in edges]
    lines += ["```", ""]
    for node, items in trees.items():
        lines += [f"## {node}", ""] + [f"- {it}" for it in items] + [""]
    return "\n".join(lines)


def samples() -> dict[str, str]:
    words = "check the input then write the result and report back to the caller when done".split()
    item = lambda k, n: " ".join(words[(k * 3) % 7 : (k * 3) % 7 + n])  # noqa: E731
    chain = [f"step_{i}" for i in range(8)]
    branchy_edges = [("[*]", "root")]
    for i in range(3):
        branchy_edges.append(("root", f"part_{i}"))
        branchy_edges += [(f"part_{i}", f"leaf_{i}{j}") for j in range(2)]
    branchy_nodes = sorted({n for e in branchy_edges for n in e} - {"[*]"})
    cyc = ["idle", "loading", "ready", "editing", "saving", "error"]
    cyc_edges = (
        [("[*]", "idle")] + list(zip(cyc, cyc[1:])) + [("saving", "ready"), ("error", "idle"), ("loading", "error")]
    )
    big_edges = [("[*]", "n00")] + [(f"n{(i - 1) // 3:02d}", f"n{i:02d}") for i in range(1, 20)]
    big_nodes = [f"n{i:02d}" for i in range(20)]
    return {
        "door (examples/)": EXAMPLE.read_text("utf-8"),
        "chain-8": design_md(
            "chain",
            [("[*]", chain[0])] + list(zip(chain, chain[1:])),
            {n: [item(i, 2 + i % 3), item(i + 1, 3)] for i, n in enumerate(chain)},
        ),
        "branchy-10": design_md(
            "branchy", branchy_edges, {n: [item(i, 3)] * (1 + i % 3) for i, n in enumerate(branchy_nodes)}
        ),
        "cycle-6": design_md("cycle", cyc_edges, {n: [item(i, 4), item(i + 2, 2)] for i, n in enumerate(cyc)}),
        "tree-20": design_md("tree", big_edges, {n: [item(i, 2)] for i, n in enumerate(big_nodes) if i % 2 == 0}),
    }


# ---------- the scenario, in the page's own code ----------

SCENARIO = r"""
const R = {};
open(MD);
const firstPos = clone(DZ.pos);
R.open = { ...legibility(), ...spacing() };
open(MD); R.deterministic = JSON.stringify(DZ.pos) === JSON.stringify(firstPos);
// a saved layout reopens unchanged
open(MD, firstPos); R.reopenSavedMaxMove = moved(firstPos, DZ.pos).max;

// n: add a linked node from the active one, three times, naming each (Enter in its name box)
open(MD);
R.insert = [];
for (let k = 0; k < 3; k++) {
  const parent = DZ.active, model0 = clone(DZ.pos), screen0 = screenPos(), z0 = DZ.zoom, B0 = boxes();
  key('n');
  const id = DZ.active, rn = DZ.rename;
  const afterAdd = screenPos();
  if (rn) dzRenameCommit(rn, `added_step_${k}`);
  const nid = DZ.active, B = boxes(), nb = B[nid];
  const hits = Object.entries(B).filter(([o, b]) => o !== nid && b[0] < nb[2] && nb[0] < b[2] && b[1] < nb[3] && nb[1] < b[3]).map(([o]) => o);
  R.insert.push({
    parent, modelMaxMove: moved(model0, DZ.pos).max, screenMaxMoveOnAdd: moved(screen0, afterAdd).max,
    screenMaxMoveOnName: moved(afterAdd, screenPos(), [id]).max, zoomChanged: DZ.zoom !== z0,
    offsetFromParent: [DZ.pos[nid][0] - model0[parent][0], DZ.pos[nid][1] - model0[parent][1]],
    newOverlaps: hits.length, overlapped: hits, gapToParentPx: Math.round(boxGap(B0[parent], nb)),
    rightOfParent: nb[0] >= B0[parent][2], inView: inView(nid).node,
  });
}
R.afterInserts = spacing();

// Enter on a node: add a tree item, then commit it
{
  const a = DZ.active, s0 = screenPos();
  dzEditNew(a, null); dzCommit(DZ.edit, 'a new tree item with a few more words in it');
  R.treeItemScreenMaxMove = moved(s0, screenPos()).max;
}

// a node typed into the Markdown (graph line added by hand)
open(MD);
{
  const m0 = clone(DZ.pos), s0 = screenPos(), src = DZ.model.nodes.find(n => n.id !== '[*]').id;
  editor.value = editor.value.replace(/stateDiagram-v2\n/, `stateDiagram-v2\n    ${src} --> typed_node\n`);
  dzRefresh();
  const B = boxes(), nb = B.typed_node;
  R.typed = {
    modelMaxMove: moved(m0, DZ.pos).max, screenMaxMove: moved(s0, screenPos()).max,
    distanceFromParent: Math.round(Math.hypot(DZ.pos.typed_node[0] - DZ.pos[src][0], DZ.pos.typed_node[1] - DZ.pos[src][1])),
    gapToParentPx: Math.round(boxGap(B[src], nb)),
    newOverlaps: Object.entries(B).filter(([o, b]) => o !== 'typed_node' && b[0] < nb[2] && nb[0] < b[2] && b[1] < nb[3] && nb[1] < b[3]).length,
    inView: inView('typed_node').node,
  };
}

// the Layout button, after a manual drag of one node; then pressed again
open(MD);
{
  const id = DZ.model.nodes.find(n => n.id !== '[*]').id;
  DZ.pos[id] = [DZ.pos[id][0] + 120, DZ.pos[id][1] + 40]; DZ.pinned = true;
  const m0 = clone(DZ.pos), z0 = DZ.zoom;
  dzLayout();
  const m1 = clone(DZ.pos);
  R.layoutButton = { modelMeanMove: moved(m0, m1).mean, modelMaxMove: moved(m0, m1).max, zoomChanged: DZ.zoom !== z0 };
  dzLayout(); R.layoutButton.secondPressMaxMove = moved(m1, DZ.pos).max;
}

// ] through every node: view changes and nodes left out of view
open(MD);
{
  let pans = 0, outOfView = 0, needless = 0, excess = 0;
  for (let k = 0; k < DZ.model.nodes.length; k++) {
    const v0 = [DZ.ox, DZ.oy, DZ.zoom];
    const next = DZ.model.nodes[(Math.max(0, DZ.model.nodes.findIndex(n => n.id === DZ.active)) + 1) % DZ.model.nodes.length].id;
    const need = minimalPan(next);
    key(']');
    excess = Math.max(excess, Math.hypot(DZ.ox - v0[0], DZ.oy - v0[1]) - need);
    const wasVisible = (() => { const z = DZ.zoom, [x, y] = DZ.pos[DZ.active]; const sx = x * v0[2] + v0[0], sy = y * v0[2] + v0[1]; return sx >= 40 && sy >= 40 && sx <= CANVAS.W - 40 && sy <= CANVAS.H - 40; })();
    const panned = DZ.ox !== v0[0] || DZ.oy !== v0[1] || DZ.zoom !== v0[2];
    pans += panned; needless += panned && wasVisible;
    outOfView += !inView(DZ.active).node;
  }
  R.cycle = { steps: DZ.model.nodes.length, pans, needlessPans: needless, nodeBoxOutOfView: outOfView, maxExcessPanPx: Math.round(excess) };
}

// keys: what each Minder default does here (state before/after)
R.keys = {};
for (const [name, k, mods] of KEYS) {
  open(MD);
  const first = DZ.model.nodes.find(n => n.id !== '[*]').id;
  DZ.active = first;
  const before = { n: DZ.model.nodes.length, md: editor.value, active: DZ.active, view: [DZ.ox, DZ.oy, DZ.zoom].join() };
  let err = null;
  try { key(k, mods || {}); } catch (e) { err = String(e); }
  const fx = [];
  if (DZ.model.nodes.length > before.n) fx.push('adds node');
  if (DZ.model.nodes.length < before.n) fx.push(`removes ${before.n - DZ.model.nodes.length} of ${before.n} nodes`);
  if (DZ.rename) fx.push('name box');
  if (DZ.edit) fx.push('tree item box');
  if (DZ.active !== before.active) fx.push('selects ' + DZ.active);
  if (DZ.link) fx.push('link mode');
  if ([DZ.ox, DZ.oy, DZ.zoom].join() !== before.view) fx.push('view changes');
  if (editor.value !== before.md && !fx.includes('adds node') && !fx.some(f => f.startsWith('removes'))) fx.push('edits Markdown');
  R.keys[name] = err ? 'error: ' + err : fx.join(', ') || 'nothing';
}
process.stdout.write(JSON.stringify(R));
"""

# Minder's default bindings (src/Shortcuts.vala) and the nearest key here
KEYS = [
    ["Tab (Minder: add child)", "Tab", None],
    ["Enter (Minder: add sibling)", "Enter", None],
    ["n (treedit: add linked node)", "n", None],
    ["e (Minder+treedit: edit)", "e", None],
    ["F2 (treedit: rename)", "F2", None],
    ["Right (Minder: select right)", "ArrowRight", None],
    ["Down (Minder: select down)", "ArrowDown", None],
    ["Delete (Minder: remove node)", "Delete", None],
    ["Ctrl+1 (Minder: zoom to fit)", "1", {"ctrlKey": True}],
    ["Ctrl+2 (Minder: zoom to selected)", "2", {"ctrlKey": True}],
    ["Ctrl+0 (Minder: actual size)", "0", {"ctrlKey": True}],
    ["Shift+C (Minder: centre node)", "C", {"shiftKey": True}],
]


def measure(md: str, w: int, h: int) -> dict:
    prog = f"const CANVAS = {{W: {w}, H: {h}}};\n"
    prog += (HERE / "design_layout_harness.js").read_text("utf-8") + "\n" + page_code() + "\n"
    prog += f"const MD = {json.dumps(md)};\nconst KEYS = {json.dumps(KEYS)};\n" + SCENARIO
    out = subprocess.run([NODE, "-e", prog], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr[-3000:])
    return json.loads(out.stdout)


def measure_all() -> dict:
    return {s: {c: measure(md, *wh) for c, wh in CANVASES.items()} for s, md in samples().items()}


def main(argv: list[str]) -> None:
    data = measure_all()
    if "--json" in argv:
        print(json.dumps(data, indent=1))
        return
    for sample, per in data.items():
        print(f"\n## {sample}")
        for canvas, r in per.items():
            o, ins = r["open"], r["insert"]
            print(
                f"  {canvas:15} zoom {o['zoom']:.2f} node {o['nodePx']}px tree {o['treePx']}px | "
                f"overlaps {o['overlaps']} minGap {o['minGapPx']}px medGap {o['medianNearestGapPx']}px "
                f"white {o['whitespaceRatio']} cross {o['crossings']} | "
                f"n: screen move {[i['screenMaxMoveOnAdd'] for i in ins]} name {[i['screenMaxMoveOnName'] for i in ins]} "
                f"overlaps {[i['newOverlaps'] for i in ins]} | item {r['treeItemScreenMaxMove']} | "
                f"typed {r['typed']} | layout {r['layoutButton']} | cycle {r['cycle']}"
            )
    print("\n## keys (door, first canvas)")
    for k, v in data["door (examples/)"][next(iter(CANVASES))]["keys"].items():
        print(f"  {k:36} {v}")


if __name__ == "__main__":
    main(sys.argv[1:])
