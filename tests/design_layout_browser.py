"""Measure design mode in a real browser: rendered font size, real box overlaps, view shift on insert.

The node harness (design_layout_eval.py) estimates box sizes; this checks them against the DOM.
Needs Playwright (`uv pip install playwright`) and a Chrome (`channel="chrome"`); not part of the
test suite.

    PYTHONPATH=src python tests/design_layout_browser.py [--json]
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from design_layout_eval import EXAMPLE, samples  # noqa: E402

VIEWPORTS = {"laptop 1366x768": (1366, 768), "desktop 1920x1080": (1920, 1080)}

PROBE = r"""() => {
  const c = document.querySelector('#dz-canvas'), cr = c.getBoundingClientRect();
  const text = document.querySelector('.dz-node text');
  const rects = [...document.querySelectorAll('.dz-node rect, .dz-item')].map(e => {
    const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom, e.tagName];
  });
  let overlaps = 0;
  for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
    const a = rects[i], b = rects[j];
    if (a[0] < b[2] - 1 && b[0] < a[2] - 1 && a[1] < b[3] - 1 && b[1] < a[3] - 1) overlaps++;
  }
  // each mind-map item is sized from dzTextW's estimate; the real text must fit in it (scroll size within 1px)
  const est = [...document.querySelectorAll('.dz-item')].map(e => [e.scrollWidth, e.clientWidth, e.scrollHeight, e.clientHeight]);
  const nodes = {};
  for (const g of document.querySelectorAll('.dz-node')) {
    const r = g.getBoundingClientRect(); nodes[g.dataset.id] = [r.left + r.width / 2, r.top + r.height / 2];
  }
  return {
    canvas: [Math.round(cr.width), Math.round(cr.height)], zoom: DZ.zoom,
    nodeFontCss: text && parseFloat(getComputedStyle(text).fontSize),
    nodeTextPx: text && Math.round(parseFloat(getComputedStyle(text).fontSize) * DZ.zoom * 10) / 10,
    renderedOverlaps: overlaps, itemTextOverflows: est.filter(([sw, cw, sh, ch]) => sw > cw + 1 || sh > ch + 1).length, items: est.length, nodes,
  };
}"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def shift(a, b):
    common = set(a) & set(b)
    d = [((a[k][0] - b[k][0]) ** 2 + (a[k][1] - b[k][1]) ** 2) ** 0.5 for k in common]
    return round(max(d), 1) if d else 0.0


def main():
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="treedit-layout-"))
    names, docs = {}, samples()
    for vi in range(len(VIEWPORTS)):  # a fresh copy per viewport: the insert below edits the file
        for i, (name, md) in enumerate(docs.items()):
            (root / f"v{vi}s{i}.md").write_text(md)
            names[name] = f"s{i}.md"
    port = free_port()
    env = dict(os.environ, PYTHONPATH=str(EXAMPLE.parents[1] / "src"))
    srv = subprocess.Popen(
        [sys.executable, "-m", "treedit", "open", str(root), "--headless", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    out = {}
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        with sync_playwright() as p:
            br = p.chromium.launch(channel="chrome", headless=True)
            for vi, (vname, (w, h)) in enumerate(VIEWPORTS.items()):
                for name, f in names.items():
                    ctx = br.new_context(viewport={"width": w, "height": h})  # fresh localStorage: no saved layout
                    pg = ctx.new_page()
                    pg.goto(f"http://127.0.0.1:{port}/#v{vi}{f}")
                    pg.wait_for_function(
                        "typeof DZ !== 'undefined' && document.querySelector('#b-design') && !document.querySelector('#b-design').hidden"
                    )
                    if not pg.evaluate("DZ.on"):
                        pg.click("#b-design")
                    pg.wait_for_selector(".dz-node")
                    pg.wait_for_timeout(300)
                    r = pg.evaluate(PROBE)
                    pg.focus("#dz-canvas")
                    pg.keyboard.press("n")
                    pg.wait_for_timeout(200)
                    pg.keyboard.type("added")
                    pg.keyboard.press("Enter")
                    pg.wait_for_timeout(300)
                    r2 = pg.evaluate(PROBE)
                    r["afterInsert"] = {
                        "zoom": r2["zoom"],
                        "renderedOverlaps": r2["renderedOverlaps"],
                        "screenShiftPx": shift(r["nodes"], r2["nodes"]),
                    }
                    del r["nodes"]
                    out.setdefault(name, {})[vname] = r
                    ctx.close()
            br.close()
    finally:
        srv.terminate()
        srv.wait()
        shutil.rmtree(root, ignore_errors=True)
    if "--json" in sys.argv:
        print(json.dumps(out, indent=1))
        return
    for name, per in out.items():
        for vname, r in per.items():
            print(
                f"{name:18} {vname:18} canvas {r['canvas']} zoom {r['zoom']:.2f} node text {r['nodeTextPx']}px "
                f"overlaps {r['renderedOverlaps']} -> {r['afterInsert']['renderedOverlaps']} "
                f"insert shift {r['afterInsert']['screenShiftPx']}px items {r['items']} text overflowing {r['itemTextOverflows']}"
            )


if __name__ == "__main__":
    main()
