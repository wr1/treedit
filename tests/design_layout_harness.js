// Design-mode layout eval harness: runs page.html's real Design-mode code (designCore + the dz* view
// functions, spliced in by design_layout_eval.py) against a stub DOM, and measures what a user would see.
// Everything here is measurement; no layout logic of its own.

/* ---------- a stub DOM, just enough for dzRender and friends ---------- */
function stubEl(tag = 'div') {
  const e = {
    tag, attrs: {}, style: {}, children: [], className: '', textContent: '', hidden: false, disabled: false,
    clientWidth: CANVAS.W, clientHeight: CANVAS.H, classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
    append(...c) { this.children.push(...c); }, replaceChildren() { this.children = []; },
    addEventListener() {}, focus() {}, select() {}, setSelectionRange() {},
    getBoundingClientRect() { return { left: 0, top: 0, width: CANVAS.W, height: CANVAS.H }; },
    get isConnected() { return true; },
  };
  return e;
}
const ELS = {};
const $ = s => (ELS[s] ||= stubEl());
const el = (tag, cls, text) => { const e = stubEl(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const document = { createElementNS: (ns, tag) => stubEl(tag), createElement: tag => stubEl(tag) };
const editor = { value: '', readOnly: false, scrollTop: 0, clientHeight: 600, focus() {}, setSelectionRange() {} };
const replaceRange = (ta, a, b, text) => { ta.value = ta.value.slice(0, a) + text + ta.value.slice(b); };
const S = { file: null }, MDP = { on: false }, H = {};
const api = async () => ({});
const toast = () => {}, syncHL = () => {}, renderMarks = () => {}, updatePos = () => {}, updateFbButton = () => {};
const resetMdPreview = () => {}, load = (k, d) => d, store = () => {}, isMarkdown = () => true, histStep = () => false;
const lineBox = () => () => [0, 0];
const undoKey = e => (!(e.ctrlKey || e.metaKey) || e.altKey ? 0 : e.key.toLowerCase() === 'z' ? (e.shiftKey ? 1 : -1) : 0);
const requestAnimationFrame = () => 0;
const setTimeout = () => 0, clearTimeout = () => {};  // dzSavePos's debounce: never fires (no server here)

/* ---------- geometry of what is on screen ---------- */
const FONT = { node: 12.5, tree: 12, edgeLabel: 11 };  // CSS px: .dz-node text, .dz-tree, .dz-elabel
function boxes() {  // model-space [l, t, r, b] per node, from dzExtent (node + its tree overlay, an estimate)
  const out = {};
  for (const n of DZ.model.nodes) { const [l, t, r, b] = dzExtent(n.id), [x, y] = DZ.pos[n.id]; out[n.id] = [x - l, y - t, x + r, y + b]; }
  return out;
}
const scr = ([l, t, r, b]) => [l * DZ.zoom + DZ.ox, t * DZ.zoom + DZ.oy, r * DZ.zoom + DZ.ox, b * DZ.zoom + DZ.oy];
const screenPos = () => Object.fromEntries(Object.entries(DZ.pos).map(([id, [x, y]]) => [id, [x * DZ.zoom + DZ.ox, y * DZ.zoom + DZ.oy]]));
function unionArea(rs) {  // exact area of a union of rectangles (coordinate compression)
  const xs = [...new Set(rs.flatMap(r => [r[0], r[2]]))].sort((a, b) => a - b);
  let area = 0;
  for (let i = 0; i + 1 < xs.length; i++) {
    const a = xs[i], b = xs[i + 1], iv = rs.filter(r => r[0] <= a && r[2] >= b).map(r => [r[1], r[3]]).sort((p, q) => p[0] - q[0]);
    if (!iv.length) continue;
    let cov = 0, [s, e] = iv[0];
    for (const [p, q] of iv.slice(1)) { if (p > e) { cov += e - s; s = p; e = q; } else e = Math.max(e, q); }
    area += (b - a) * (cov + e - s);
  }
  return area;
}
function crossings() {
  const segs = DZ.model.edges.filter(e => e.from !== e.to).map(e => [e.from, e.to, DZ.pos[e.from], DZ.pos[e.to]]);
  const ccw = (a, b, c) => (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0]);
  let n = 0;
  for (let i = 0; i < segs.length; i++) for (let j = i + 1; j < segs.length; j++) {
    const [a1, a2, p1, p2] = segs[i], [b1, b2, q1, q2] = segs[j];
    if ([a1, a2].some(x => x === b1 || x === b2)) continue;
    if (ccw(p1, p2, q1) * ccw(p1, p2, q2) < 0 && ccw(q1, q2, p1) * ccw(q1, q2, p2) < 0) n++;
  }
  return n;
}
function spacing() {  // screen px, after the view transform
  const B = Object.values(boxes()).map(scr), ids = Object.keys(DZ.pos);
  let overlaps = 0, overlapArea = 0;
  const nearest = B.map(() => Infinity);
  for (let i = 0; i < B.length; i++) for (let j = i + 1; j < B.length; j++) {
    const [a, b] = [B[i], B[j]];
    const gx = Math.max(b[0] - a[2], a[0] - b[2]), gy = Math.max(b[1] - a[3], a[1] - b[3]);
    if (gx < 0 && gy < 0) { overlaps++; overlapArea += gx * gy; }
    const g = Math.max(gx, gy);  // separation along the axis that separates them (negative: overlap)
    nearest[i] = Math.min(nearest[i], g); nearest[j] = Math.min(nearest[j], g);
  }
  const all = [Math.min(...B.map(b => b[0])), Math.min(...B.map(b => b[1])), Math.max(...B.map(b => b[2])), Math.max(...B.map(b => b[3]))];
  const bboxArea = (all[2] - all[0]) * (all[3] - all[1]), u = unionArea(B);
  const sorted = nearest.filter(Number.isFinite).sort((a, b) => a - b);
  return {
    nodes: ids.length, overlaps, overlapAreaFrac: +(overlapArea / (u || 1)).toFixed(3),
    minGapPx: sorted.length ? +sorted[0].toFixed(1) : null,
    medianNearestGapPx: sorted.length ? +sorted[Math.floor(sorted.length / 2)].toFixed(1) : null,
    whitespaceRatio: +(1 - u / (bboxArea || 1)).toFixed(3),
    fillOfCanvas: +(u / (CANVAS.W * CANVAS.H)).toFixed(3),
    crossings: crossings(),
  };
}
const legibility = () => ({ zoom: +DZ.zoom.toFixed(3), nodePx: +(FONT.node * DZ.zoom).toFixed(1), treePx: +(FONT.tree * DZ.zoom).toFixed(1), edgeLabelPx: +(FONT.edgeLabel * DZ.zoom).toFixed(1) });
function moved(before, after, skip = []) {  // max / mean displacement (px) of the ids in BEFORE
  const ds = Object.keys(before).filter(id => after[id] && !skip.includes(id)).map(id => Math.hypot(after[id][0] - before[id][0], after[id][1] - before[id][1]));
  return { max: ds.length ? +Math.max(...ds).toFixed(1) : 0, mean: ds.length ? +(ds.reduce((a, b) => a + b, 0) / ds.length).toFixed(1) : 0, n: ds.length };
}
const clone = o => JSON.parse(JSON.stringify(o));
function inView(id, pad = 0) {
  const [l, t, r, b] = scr(boxes()[id]);
  return { node: l >= pad && t >= pad && r <= CANVAS.W - pad && b <= CANVAS.H - pad, centre: (() => { const [x, y] = screenPos()[id]; return x >= 0 && y >= 0 && x <= CANVAS.W && y <= CANVAS.H; })() };
}
function boxGap(a, b) {  // separation of two [l, t, r, b] boxes along the axis that separates them (negative: overlap)
  return Math.max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3]);
}
function minimalPan(id, margin = 40) {  // the smallest view shift (px) that brings the node's centre inside the margin dzEnsureVisible uses
  const [x, y] = screenPos()[id], over = (v, max) => (v < margin ? margin - v : v > max - margin ? v - (max - margin) : 0);
  return Math.hypot(over(x, CANVAS.W), over(y, CANVAS.H));
}
const key = (k, mods = {}) => dzKey({ key: k, target: {}, preventDefault() {}, stopPropagation() {}, ...mods });

/* ---------- opening a file the way setDesign does (no saved layout, or a given one) ---------- */
function open(md, saved = null) {
  Object.assign(DZ, { on: true, path: 'x.md', link: false, said: '', pos: saved ? clone(saved) : {}, active: null, drag: null, pinned: false,
    edit: null, press: null, rename: null, label: null, zoom: 1, fitNext: true, folded: new Set() });
  editor.value = md;
  dzRefresh();
}
