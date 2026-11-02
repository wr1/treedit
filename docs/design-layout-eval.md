# Design-mode layout: evaluation criteria, baseline, direction

Design mode works, but its layout has quirks: nodes get jumbled, the spacing is so wide that the text
ends up too small to read, and the view feels jittery. The yardstick is Minder, whose defaults just
work. This page sets out testable criteria, what the current code measures against them, and the
changes that should help most, in order.

Everything here runs from the repo:

| what | how |
|---|---|
| headless measurements (the page's real `designCore` + `dz*` code in node, stub DOM) | `make layout-eval` or `uv run python tests/design_layout_eval.py [--json]` |
| criteria as tests: met = assert, missed = `xfail(strict=True)` | `tests/test_design_layout_eval.py` (part of `make test`) |
| real-browser check of fonts, real box sizes and overlaps (Playwright + Chrome, not in the suite) | `PYTHONPATH=src python tests/design_layout_browser.py` |

Samples:

- `examples/door-design.md`;
- synthetic design files from `design_layout_eval.samples()`:
  - `chain-8`: a linear chain of 8;
  - `branchy-10`: a fan-out of 10;
  - `cycle-6`: 6 nodes with back edges;
  - `tree-20`: a 3-ary tree of 20.

Canvas sizes: the design canvas measured in a real browser window, 637×264 px at 1366×768 and 896×645
px at 1920×1080.

## What Minder does by default

All links point to [phase1geo/Minder @ e6117cf](https://github.com/phase1geo/Minder/tree/e6117cf1eada82925dd87b696bb05129fbe992e5).

- **Deterministic tree layouts, not force-directed.**
  - The default layout is *Horizontal*: [`Layouts.vala` `get_default()`](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/Layouts.vala#L84-L86) returns index 2.
  - Root trees sit `_rt_gap = 100` apart: [`Layout.vala` L24](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/Layout.vala#L24).
- **Fixed, small spacing.**
  - [`Styles.vala` L91-L108](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/Styles.vala#L91-L108) sets `branch_margin = 100` between a parent and its children.
  - The same lines set `node_margin` 8 (10 for the root) and `node_padding` 6 (10 for the root).
  - `node_width` is 300.
  - Text is 12 pt: [`CanvasText.vala` L50](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/CanvasText.vala#L50).
- **Opens at actual size.** `sfactor = 1.0`: [`DrawArea.vala` L392](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/DrawArea.vala#L392).
  - Zoom-to-fit is a command you ask for: [`zoom_to_fit` L1004](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/DrawArea.vala#L1004).
  - So are [`zoom_actual` L1024](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/DrawArea.vala#L1024), [`zoom_to_selected` L989](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/DrawArea.vala#L989) and [`center_node` L1041](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/DrawArea.vala#L1041).
- **Incremental placement.** [`handle_update_by_insert`](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/Layout.vala#L406) places a new child as follows:
  - It sits `branch_margin` beyond its parent.
  - An only child sits on the parent's plane.
  - Otherwise it goes next to its sibling's subtree.
  - Then [`adjust_tree_all`](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/Layout.vala#L216) shifts only the siblings and ancestors by the space the new child needs. Nothing else is re-solved.
  - Edits, folds and deletes are local adjustments in the same way ([L389](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/Layout.vala#L389), [L395](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/Layout.vala#L395)).
- **Minimal, animated pans.**
  - [`see()` L1061-L1110](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/DrawArea.vala#L1061-L1110) runs on each selection change ([`MindMap.vala` L250](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/MindMap.vala#L250)).
  - It pans only when the selected node plus 100 px of padding would leave the view, and then only by the overflow.
  - It zooms out only when the node cannot fit.
  - Pans animate over 10 frames 20 ms apart, about 200 ms ([`Animator.vala` L28-L29](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/Animator.vala#L28-L29)). A setting can turn the animation off (`enable-animations` in the gschema).
- **Keys that just work** ([`Shortcuts.vala` L522-L681](https://github.com/phase1geo/Minder/blob/e6117cf1eada82925dd87b696bb05129fbe992e5/src/Shortcuts.vala#L522-L681)):

  | action | key |
  |---|---|
  | add child / add parent | Tab / Shift+Tab |
  | add sibling after / before | Return / Shift+Return |
  | select | arrows, or h j k l |
  | previous / next sibling | Page Up / Page Down |
  | edit | e |
  | remove | Delete |
  | undo | Ctrl+Z |
  | actual size / fit / selected | Ctrl+0 / Ctrl+1 / Ctrl+2 |
  | zoom in / out | Ctrl+plus / Ctrl+minus |
  | centre the node | Shift+C |

## Criteria and measured baseline

All thresholds are **proposed** and come with their reasons. Each "baseline" figure was measured by
the scripts above at commit time, across 5 samples × 2 canvases = 10 runs. "Worst" is the worst of the 10.

| # | criterion | metric (where it is measured) | proposed threshold, and why | baseline | |
|---|---|---|---|---|---|
| S1 | no overlaps at open | box overlaps (node + tree overlay estimate), `open.overlaps` | 0 | 0 in 10/10 runs; real DOM: 0 in 10/10 | ✅ |
| S2 | readable gap | smallest screen gap between boxes, `open.minGapPx` | ≥ 12 px: about one line of the 12 px tree text | 9.4–74.9 px; misses door@637×264 (10.4) and tree-20@637×264 (9.4) | ❌ |
| S3 | not too much white | 1 − (box area ÷ drawing bounding box), `open.whitespaceRatio` | ≤ 0.75: at least a quarter of the drawing is content | door 0.692; cycle 0.829; branchy 0.949; chain 0.961; tree 0.987 | ❌ (4/5 samples) |
| S4 | median gap no larger than a Minder branch | `open.medianNearestGapPx` at a legible zoom | ≤ 100 px (Minder `branch_margin`) | door@896×645, the only legible run: 113.4 px | ❌ |
| L1 | text legible at default zoom | `open.nodePx` / `treePx` = CSS px × zoom | ≥ 11 px: the page's own smallest text (`.dz-elabel` 11px); Minder opens at 1.0 with 12 pt | node text 0.9–12.5 px; legible in 1/10 runs (door@896×645). Real browser: 0.8–12.5 px, also 1/10 | ❌ |
| T1 | existing nodes keep their place on insert / typing | max model displacement of existing nodes, `insert[].modelMaxMove`, `typed.modelMaxMove` | 0 (Minder moves only siblings and ancestors, and those only to make room) | 0 in 10/10 runs | ✅ |
| T2 | deterministic | same file twice → same layout, and a saved layout reopens unchanged | identical, 0 px | identical, 0 px in 10/10 runs | ✅ |
| T3 | view holds still on edit | max screen shift of existing nodes on add, name, tree-item add and typed node, when nothing needs revealing | ≤ 2 px (rounding) | worst 245.4 px (cycle-6@637×264 add); door: 13.1–52 px; 0 px on branchy-10 and tree-20 | ❌ |
| T4 | Layout button keeps the user's work | after a +120,+40 drag, the Layout button's model move; and a second press | the dragged node stays put (proposed); a second press moves 0 | dragged node snaps back 126.5 px in 10/10 runs; second press 0 | ❌ / ✅ |
| P1 | new node does not land on anything | `insert[].newOverlaps`, `afterInserts.overlaps` | 0 | the first `n` overlaps the parent's tree overlay in 10/10 runs; 1–3 overlaps after 3 inserts. Real DOM: 0 → 0–14 after one insert, varying run to run | ❌ |
| P2 | new node goes where Minder puts it | gap from the parent box to the new box (`gapToParentPx`, `rightOfParent`); a node typed into the Markdown (`typed.gapToParentPx`) | 8–100 px (Minder `node_margin`..`branch_margin`), on a consistent side | `n`: gaps −81 to 4 px, never right of the parent; typed node: 161–237 px away | ❌ |
| F1 | new or selected node in view | `inView` after insert, typing, cycling | always | inserts 30/30; typed node out of view in cycle-6@637×264 | ❌ (1 run) |
| F2 | no needless pans | pans while cycling (`]`) when the node was already visible | 0 | 0 in 10/10 runs | ✅ |
| F3 | pans are minimal | pan distance minus the smallest pan that reveals the node (`cycle.maxExcessPanPx`) | ≤ 20 px (Minder `see()` pans by the overflow) | 0 only on door@896×645; otherwise 105–436 px (`dzEnsureVisible` re-centres) | ❌ |
| K1 | the Minder keys work, without the mouse | key → observed effect on door (`keys`) | add child, add sibling, edit, navigate, delete, fit, actual size, zoom to selected and centre all reachable | 4 of 9 (see below) | ❌ |

What each key does on the door example (first canvas):

| key | Minder | treedit now |
|---|---|---|
| Tab | add child | nothing (`n` adds a linked node and opens its name box) |
| Enter | add sibling | opens a tree-item box (adds no node) |
| e / F2 | edit | name box ✅ |
| arrows | select by direction | walk along edges ✅ (Right → `[*]`, Down → `Open`) |
| Delete | remove node | removes it; on door's `Closed`, **all 4 of 4 nodes go**, because `[*]`, `Open` and `Locked` exist only through edges to `Closed` (their `##` sections stay in the Markdown) |
| Ctrl+1 / Ctrl+0 / Ctrl+2 | fit / actual size / selected | nothing (Fit is a button only) |
| Shift+C | centre node | nothing |

The test file asserts T1, T2, the second-press half of T4, S1 and F2. It marks S2/S3, L1, P1, P2,
T3, F1/F3 and K1 as strict xfails, so a fix that meets one of them shows up as an XPASS.

### What the real browser adds (`design_layout_browser.py`)

- **The canvas is small on a laptop.** It is 637×264 px in a 1366×768 window and 896×645 px at 1920×1080, which is why the fit-all zoom drops so far.
- **The tree-size estimate is off.** `dzExtent`, which `dzFit` and fit-all rely on, gives box sizes that differ from the rendered DOM:
  - widths are over-estimated by 17–54%;
  - heights are off by −38% to +197%;
  - the height is under-estimated whenever items wrap.

  So the collision avoidance is working from the wrong boxes.

## Not measurable headlessly (and the check I'd use)

- **Perceived jitter and animation.** The page has no animation: each render jumps. Node gives only per-step displacement (T3, F3), not how it feels.
  - Check: in Chrome, wrap `dzRender` to log `(ox, oy, zoom)` with `performance.now()`.
  - Then count the view changes per second during typing and naming. The target is 0 when nothing needs revealing.
  - Optionally record a screencast via CDP `Page.startScreencast`.
- **Real text and box metrics in the node runs.** The node harness uses `dzExtent`'s estimate. The browser script measures the real DOM, but only at open and after one insert.
- **Undo (Ctrl+Z).** The harness stubs the history, so undo is not measured.
- **Resizing the window or the split.** `ResizeObserver` (page.html L3362) unpins the view, and the next render re-centres it. This is not exercised.

## Prioritised direction

The changes are ranked by how many failing metrics they fix and how much those metrics matter to "text
too small" and "jittery". The line numbers refer to `src/treedit/page.html` at this commit.

1. **Open at a legible zoom, not fit-all.** Fixes L1, S2 and S4 (the "text too small" complaint).
   - Code: `dzRender` L3269 (`fitNext` → `zoom = min(1, W/w, H/h)`), set by `dzFit` L2971 and `dzFitView` L2982.
   - Floor the automatic zoom at 1.0 (or ≥ 0.88, which is 11 px node text) and frame the active node or the root with a `see()`-style pan.
   - Keep fit-all for an explicit command (the button, plus Ctrl+1).
2. **Stop re-centring on every render.** Fixes T3 and F3 (the "jittery" complaint).
   - Code: the `!DZ.pinned` branch of `dzRender` L3265-L3272 recomputes `ox`/`oy` from the drawing's bounds on every edit. `dzEnsureVisible` L3205 re-centres; `ResizeObserver` L3362 unpins.
   - Set the view once at open. After that, move it only through Minder's `see()` rule: when the active box plus padding would leave the view, pan by the overflow.
   - Optionally animate that over about 200 ms.
3. **Place new nodes the Minder way, using the real boxes.** Fixes P1 and P2 (the "jumbled" complaint).
   - Code: `dzAddNode` L2989-L3000 puts the node at +90,+60 from the parent's centre and checks only against other nodes' *centres*, so it lands inside the parent's tree overlay.
   - Code: the `dzRefresh` partial layout L2914 runs the force solver for nodes typed into the Markdown, which places them 161–237 px from their parent.
   - Place a new child `branch_margin` (≈100 px) to the right of the parent's full extent (`dzExtent`), level with the parent if it is the only child, otherwise below the last sibling's extent.
   - Then push away only what it now overlaps.
   - Measure trees from the DOM after render (or cache the measured sizes) instead of the `dzExtent` estimate (L2946-L2953; real heights are up to +197% off).
4. **A tidy layered layout instead of force-directed.** Fixes S3, S4, T4 and the overlaps.
   - Code: `designCore().layout` L2659 (force, `K = 230` at L2665, 300 iterations) plus `dzFit` L2954.
   - Use a deterministic layered or tree layout along the `[*]`-rooted spanning tree: horizontal like Minder's default, with fixed gaps (about 100 px between ranks, about 16 px between siblings, using the boxes including their trees).
   - Draw back edges as curves.
   - Make the Layout button (`dzLayout` L2983) keep nodes the user dragged, or have it ask first.
5. **Minder's default keys.** Fixes K1.
   - Code: `dzKey` L3175.
   - Tab: add a linked child (= `n`).
   - Enter on a node: add a sibling (a node linked from the active node's parent). Move "add tree item" to Shift+Enter or `i`, keeping the button.
   - Ctrl+1 fit, Ctrl+0 actual size, Ctrl+2 zoom to selected, Shift+C centre.
   - Separately, make Delete keep neighbours that would be orphaned (keep them as bare state declarations) rather than dropping 4 of 4 nodes.

Remeasure after each step with `make layout-eval`, and turn the matching xfail in
`tests/test_design_layout_eval.py` into a plain assert.
