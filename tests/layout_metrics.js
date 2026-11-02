// layoutMetrics(scene, view, canvas): Minder-style layout quality numbers for one Design-mode picture.
// Pure: no DOM, no page state. Used by design_layout_harness.js (node) and usable in a browser console.
//
// scene, in model px:
//   nodes: { id: [l, t, r, b] }                        the state boxes
//   maps:  { id: { box: [l, t, r, b] | null,           the mind map's bounding box (null: folded or no tree)
//                  items: [{ box, parent, key }] } }   item boxes; parent = index of the parent item, -1 = the state
//   edges: [{ from, to, pts: [[x, y], ...] }]          each state edge as the polyline that is drawn
// view: { ox, oy, zoom }   canvas: { W, H }   fonts: CSS px of node and tree text
function layoutMetrics(scene, view, canvas, fonts = { node: 12.5, tree: 12 }) {
  const ids = Object.keys(scene.nodes), z = view.zoom;
  const overlap = (a, b, pad = 0) => a[0] < b[2] + pad && b[0] < a[2] + pad && a[1] < b[3] + pad && b[1] < a[3] + pad;
  const shrink = (r, d) => [r[0] + d, r[1] + d, r[2] - d, r[3] - d];
  const segHits = (p, q, r) => {  // Liang-Barsky: does segment p-q pass through rect r
    let t0 = 0, t1 = 1;
    const dx = q[0] - p[0], dy = q[1] - p[1];
    for (const [pp, qq] of [[-dx, p[0] - r[0]], [dx, r[2] - p[0]], [-dy, p[1] - r[1]], [dy, r[3] - p[1]]]) {
      if (pp === 0) { if (qq < 0) return false; continue; }
      const t = qq / pp;
      if (pp < 0) { if (t > t1) return false; if (t > t0) t0 = t; } else { if (t < t0) return false; if (t < t1) t1 = t; }
    }
    return t0 < t1;
  };
  const segs = e => e.pts.slice(1).map((q, i) => [e.pts[i], q]);
  const mapRects = id => { const m = scene.maps[id]; return m && m.box ? m.items.map(it => it.box) : []; };
  const S = {};
  // legibility at the view's zoom
  S.zoom = +z.toFixed(3); S.nodePx = +(fonts.node * z).toFixed(1); S.treePx = +(fonts.tree * z).toFixed(1);
  // (a) states: node/node overlaps
  S.stateOverlaps = 0;
  for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) S.stateOverlaps += overlap(scene.nodes[ids[i]], scene.nodes[ids[j]]);
  // (b) vs (a): a mind map over another state, another mind map, or any edge
  S.mapStateOverlaps = 0; S.mapMapOverlaps = 0; S.edgeMapHits = 0; S.edgeNodeHits = 0;
  for (const a of ids) for (const r of mapRects(a)) {
    for (const b of ids) if (overlap(shrink(r, 0.5), scene.nodes[b])) S.mapStateOverlaps++;
    for (const b of ids) if (b > a) for (const q of mapRects(b)) if (overlap(shrink(r, 0.5), q)) S.mapMapOverlaps++;
  }
  for (const e of scene.edges) for (const [p, q] of segs(e)) {
    for (const a of ids) for (const r of mapRects(a)) if (segHits(p, q, shrink(r, 0.5))) S.edgeMapHits++;
    for (const a of ids) if (a !== e.from && a !== e.to && segHits(p, q, shrink(scene.nodes[a], 0.5))) S.edgeNodeHits++;
  }
  // (b) inside: consistent sibling spacing, branch gap from the parent, reach from the state
  const sib = [], branch = [];
  let reach = 0;
  for (const a of ids) {
    const m = scene.maps[a];
    if (!m || !m.box) continue;
    const n = scene.nodes[a], byParent = new Map();
    m.items.forEach((it, i) => { (byParent.get(it.parent) || byParent.set(it.parent, []).get(it.parent)).push(it); });
    for (const kids of byParent.values()) {
      const ys = kids.map(k => k.box).sort((p, q) => p[1] - q[1]);
      for (let i = 1; i < ys.length; i++) sib.push(ys[i][1] - ys[i - 1][3]);
    }
    for (const it of m.items) {
      const pb = it.parent < 0 ? n : m.items[it.parent].box;
      if (it.box !== pb) branch.push(it.box[0] - pb[2]);
      const dx = Math.max(0, it.box[2] - n[2]), dy = Math.max(0, n[1] - it.box[1], it.box[3] - n[3]);
      reach = Math.max(reach, Math.hypot(dx, dy));
    }
  }
  const stats = v => v.length ? { min: +Math.min(...v).toFixed(1), max: +Math.max(...v).toFixed(1),
    mean: +(v.reduce((s, x) => s + x, 0) / v.length).toFixed(1),
    std: +Math.sqrt(v.reduce((s, x) => s + (x - v.reduce((t, y) => t + y, 0) / v.length) ** 2, 0) / v.length).toFixed(1) } : null;
  S.siblingGap = stats(sib); S.branchGap = stats(branch); S.mapReachPx = Math.round(reach);
  // (a) the state graph: edge lengths (centre to centre) and crossings of the drawn polylines
  const ctr = r => [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2];
  const lens = scene.edges.filter(e => e.from !== e.to).map(e => { const [p, q] = [ctr(scene.nodes[e.from]), ctr(scene.nodes[e.to])]; return Math.hypot(q[0] - p[0], q[1] - p[1]); }).sort((a, b) => a - b);
  S.edgeLen = lens.length ? { median: Math.round(lens[lens.length >> 1]), max: Math.round(lens[lens.length - 1]), ratio: +(lens[lens.length - 1] / (lens[lens.length >> 1] || 1)).toFixed(2) } : null;
  const ccw = (a, b, c) => (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0]);
  let cross = 0;
  const E = scene.edges.filter(e => e.from !== e.to);
  for (let i = 0; i < E.length; i++) for (let j = i + 1; j < E.length; j++) {
    if ([E[i].from, E[i].to].some(x => x === E[j].from || x === E[j].to)) continue;
    for (const [p1, p2] of segs(E[i])) for (const [q1, q2] of segs(E[j]))
      if (ccw(p1, p2, q1) * ccw(p1, p2, q2) < 0 && ccw(q1, q2, p1) * ccw(q1, q2, p2) < 0) cross++;
  }
  S.crossings = cross;
  // the whole picture: white space and the smallest screen gap between blocks (state + its mind map)
  const blocks = ids.map(a => { const n = scene.nodes[a], m = scene.maps[a]; return m && m.box ? [Math.min(n[0], m.box[0]), Math.min(n[1], m.box[1]), Math.max(n[2], m.box[2]), Math.max(n[3], m.box[3])] : n; });
  const rects = ids.flatMap(a => [scene.nodes[a], ...mapRects(a)]);
  const all = [Math.min(...rects.map(r => r[0])), Math.min(...rects.map(r => r[1])), Math.max(...rects.map(r => r[2])), Math.max(...rects.map(r => r[3]))];
  S.drawingPx = [Math.round((all[2] - all[0]) * z), Math.round((all[3] - all[1]) * z)];
  let minGap = Infinity;
  for (let i = 0; i < blocks.length; i++) for (let j = i + 1; j < blocks.length; j++) {
    const [a, b] = [blocks[i], blocks[j]];
    minGap = Math.min(minGap, Math.max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3]) * z);
  }
  S.minBlockGapPx = Number.isFinite(minGap) ? +minGap.toFixed(1) : null;
  return S;
}
if (typeof module !== 'undefined') module.exports = { layoutMetrics };
