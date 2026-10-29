"""Design mode's pure core (page.html designCore, run in node): parse, minimal-diff serialize, layout."""

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")
SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "door-design.md"


def js_function(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i : k + 1]
    raise ValueError(name)


@pytest.fixture(scope="module")
def lib():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    return js_function(src, "designCore") + "\nconst D = designCore();\n"


def run(lib: str, body: str, **data):
    prog = lib + "".join(f"const {k} = {json.dumps(v)};\n" for k, v in data.items())
    prog += f"process.stdout.write(JSON.stringify((() => {{ {body} }})()));"
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


FLOW = """# Pipeline

Intro prose.

```mermaid
flowchart LR
  %% comment kept
  Idle[Waiting] -->|start| Busy --> Done
  Busy -.-> Idle
  classDef hot fill:#f00
```

- Idle
  - waits for a job
- Busy
  - runs
    - step one
- Done
  - reports

Trailing text.
"""

D2 = """# D2 design

```d2
# a comment
idle -> busy: start
busy -> idle
group: {
  inner -> other
}
done
```

## idle
- waits

## busy
- works

## done
"""

STATE_CRLF = "```mermaid\r\nstateDiagram\r\n  A --> B\r\n```\r\n\r\n## A\r\n- a\r\n\r\n## B\r\n- b\r\n"


@pytest.mark.parametrize("name", ["sample", "flow", "d2", "crlf"])
def test_unedited_files_round_trip_byte_for_byte(lib, name):
    md = {"sample": SAMPLE.read_text("utf-8"), "flow": FLOW, "d2": D2, "crlf": STATE_CRLF}[name]
    assert run(lib, "return D.serialize(D.parse(md), md);", md=md) == md


def test_parse_state_sample(lib):
    m = run(lib, "return D.parse(md);", md=SAMPLE.read_text("utf-8"))
    assert m["flavor"] == "state"
    assert [n["id"] for n in m["nodes"]] == ["[*]", "Closed", "Open", "Locked"]
    assert [(e["from"], e["to"], e["label"]) for e in m["edges"]] == [
        ("[*]", "Closed", None),
        ("Closed", "Open", "open"),
        ("Open", "Closed", "close"),
        ("Closed", "Locked", "lock"),
        ("Locked", "Closed", "unlock"),
    ]
    assert sorted(m["trees"]) == ["Closed", "Locked", "Open"]
    closed = m["trees"]["Closed"]["items"]
    assert [i["text"] for i in closed] == ["entry: motor off", "accepts", "shows: green LED"]
    assert [i["text"] for i in closed[1]["children"]] == ["open (if not blocked)", "lock"]
    assert run(lib, "return D.isDesign(D.parse(md));", md=SAMPLE.read_text("utf-8")) is True


def test_parse_flowchart_chains_shapes_and_bullet_trees(lib):
    m = run(lib, "return D.parse(md);", md=FLOW)
    assert m["flavor"] == "flowchart"
    assert [n["id"] for n in m["nodes"]] == ["Idle", "Busy", "Done"]
    assert [(e["from"], e["to"], e["label"]) for e in m["edges"]] == [
        ("Idle", "Busy", "start"),
        ("Busy", "Done", None),
        ("Busy", "Idle", None),
    ]
    assert {k: t["style"] for k, t in m["trees"].items()} == {"Idle": "bullet", "Busy": "bullet", "Done": "bullet"}
    assert m["trees"]["Busy"]["items"][0]["children"][0]["text"] == "step one"


def test_parse_d2_skips_containers(lib):
    m = run(lib, "return D.parse(md);", md=D2)
    assert m["flavor"] == "d2"
    assert [n["id"] for n in m["nodes"]] == ["idle", "busy", "done"]
    assert [(e["from"], e["to"], e["label"]) for e in m["edges"]] == [("idle", "busy", "start"), ("busy", "idle", None)]
    assert sorted(m["trees"]) == ["busy", "done", "idle"]


def test_not_a_design_file(lib):
    assert run(lib, "return D.parse(md);", md='# Notes\n\n```mermaid\npie\n  "a": 1\n```\n') is None
    md = "```mermaid\nstateDiagram-v2\n  A --> B\n```\n\nNo trees here.\n"
    assert run(lib, "return D.isDesign(D.parse(md));", md=md) is False


def edit(lib, md, body):
    return run(lib, f"let m = D.parse(md), r; {body}; return {{ out: D.serialize(r.model, md), said: r.said }};", md=md)


def diff(a: str, b: str):
    import difflib

    return [
        x
        for x in difflib.unified_diff(a.split("\n"), b.split("\n"), lineterm="", n=0)
        if x[:1] in "+-" and x[:3] not in ("+++", "---")
    ]


def test_add_node_touches_only_new_lines(lib):
    md = SAMPLE.read_text("utf-8")
    r = edit(lib, md, "r = D.addNode(m)")
    assert r["said"] == "added node S1"
    assert diff(md, r["out"]) == ["+    S1", "+## S1", "+"]  # difflib aligns the blank line after it
    assert r["out"].index("    S1") > r["out"].index("Locked --> Closed")  # after the last graph line
    assert r["out"].index("## S1") < r["out"].index("## Notes")  # after the last tree, before other prose


def test_add_edge_is_one_line(lib):
    md = SAMPLE.read_text("utf-8")
    r = edit(lib, md, "r = D.addEdge(m, 'Open', 'Locked')")
    assert r["said"] == "added edge Open->Locked"
    assert diff(md, r["out"]) == ["+    Open --> Locked"]
    dup = edit(lib, md, "r = D.addEdge(m, 'Open', 'Closed')")
    assert dup["said"] == "" and dup["out"] == md


def test_delete_node_removes_its_edges_and_tree_only(lib):
    md = SAMPLE.read_text("utf-8")
    r = edit(lib, md, "r = D.deleteNode(m, 'Open')")
    assert r["said"] == "deleted node Open (2 edges, its tree)"
    assert diff(md, r["out"]) == [
        "-    Closed --> Open : open",
        "-    Open --> Closed : close",
        "-## Open",
        "-",
        "-- entry: start the 30 s timer",
        "-- on timeout: close",
        "-  - beep twice first",
        "-",
    ]
    assert "%% the door's life cycle" in r["out"] and "## Notes" in r["out"]


def test_delete_then_add_round_trips(lib):
    md = SAMPLE.read_text("utf-8")
    body = "r = D.addNode(m); const id = r.id; const md2 = D.serialize(r.model, md); m = D.parse(md2); r = D.deleteNode(m, id); return D.serialize(r.model, md2);"
    assert run(lib, "let m = D.parse(md), r; " + body, md=md) == md


def test_flowchart_chain_split_keeps_the_rest(lib):
    r = edit(lib, FLOW, "r = D.deleteNode(m, 'Done')")
    assert diff(FLOW, r["out"]) == [
        "-  Idle[Waiting] -->|start| Busy --> Done",
        "+  Idle[Waiting] -->|start| Busy",
        "-- Done",
        "-  - reports",
        "-",
    ]


def test_new_tree_follows_bullet_style_and_d2_syntax(lib):
    r = edit(lib, FLOW, "r = D.addNode(m, 'Failed'); r = D.addEdge(r.model, 'Busy', 'Failed')")
    assert diff(FLOW, r["out"]) == ["+  Busy --> Failed", "+- Failed", "+"]  # the edge declares the node
    r = edit(lib, D2, "r = D.addEdge(m, 'busy', 'done')")
    assert diff(D2, r["out"]) == ["+busy -> done"]


def test_last_tree_deleted_keeps_final_newline(lib):
    md = "```mermaid\nstateDiagram-v2\n  A --> B\n```\n\n## A\n- a\n\n## B\n- b\n"
    r = edit(lib, md, "r = D.deleteNode(m, 'B')")
    assert r["out"] == "```mermaid\nstateDiagram-v2\n```\n\n## A\n- a\n"


def test_minimal_edit_and_layout(lib):
    e = run(lib, "return D.minimalEdit('abcXdef', 'abcYYdef');")
    assert e == {"from": 3, "to": 4, "text": "YY"}
    out = run(
        lib,
        "const m = D.parse(md), ids = m.nodes.map(n => n.id); const a = D.layout(ids, m.edges, {}, null);"
        "const b = D.layout(ids, m.edges, { Closed: [5, 5] }, new Set(['Closed'])); return { a, again: D.layout(ids, m.edges, {}, null), b };",
        md=SAMPLE.read_text("utf-8"),
    )
    assert out["a"] == out["again"]  # deterministic
    assert out["b"]["Closed"] == [5, 5]  # fixed nodes stay put
    pts = list(out["a"].values())
    assert min(abs(p[0] - q[0]) + abs(p[1] - q[1]) for i, p in enumerate(pts) for q in pts[i + 1 :]) > 40


def test_starter_graph_goes_after_the_title_and_intro(lib):
    md = "---\ntags: [x]\n---\n# Title\n\nIntro.\n\n## Later\n\n- keep\n"
    out = run(lib, "return D.starter(md);", md=md)
    assert out == (
        "---\ntags: [x]\n---\n# Title\n\nIntro.\n\n## Graph\n\n```mermaid\nstateDiagram-v2\n```\n\n## Later\n\n- keep\n"
    )
    assert run(lib, "return D.starter(md);", md="") == "## Graph\n\n```mermaid\nstateDiagram-v2\n```\n"
    assert run(lib, "return D.starter(md);", md="Just prose.\n").startswith("## Graph\n\n```mermaid")
    m = run(lib, "return D.parse(D.starter(md));", md=md)
    assert (m["flavor"], m["nodes"]) == ("state", [])


def test_first_node_in_a_starter_graph(lib):
    md = run(lib, "return D.starter(md);", md="# Title\n\nIntro.\n")
    r = edit(lib, md, "r = D.addNode(m)")
    assert r["out"] == "# Title\n\nIntro.\n\n## Graph\n\n```mermaid\nstateDiagram-v2\n    S1\n```\n\n## S1\n"
    assert run(lib, "return D.isDesign(D.parse(md));", md=r["out"]) is True


TREES = """```mermaid
stateDiagram-v2
    A --> B
```

## A

- one
  - one.a
    more of one.a
  - one.b
- two

## B
"""


def tree_edit(lib, md, body):
    return run(lib, f"return {body};", md=md)


def test_set_item_and_delete_with_children(lib):
    r = tree_edit(lib, TREES, "D.setItem(md, 8, 'ONE.A')")
    assert diff(TREES, r["md"]) == ["-  - one.a", "+  - ONE.A"] and r["line"] == 8
    r = tree_edit(lib, TREES, "D.setItem(md, 7, '  ')")
    assert diff(TREES, r["md"]) == ["-- one", "-  - one.a", "-    more of one.a", "-  - one.b"]
    assert tree_edit(lib, TREES, "D.setItem(md, 4, 'x')") is None  # not an item


def test_insert_items(lib):
    r = tree_edit(lib, TREES, "D.insertItem(md, 'A', 8, 'between')")  # after one.a and its continuation line
    assert diff(TREES, r["md"]) == ["+  - between"] and r["md"].split("\n")[r["line"]] == "  - between"
    assert r["md"].split("\n")[r["line"] - 1] == "    more of one.a"
    r = tree_edit(lib, TREES, "D.insertItem(md, 'A', null, 'three')")
    assert r["md"].split("\n")[r["line"] - 1 : r["line"] + 1] == ["- two", "- three"]
    r = tree_edit(lib, TREES, "D.insertItem(md, 'B', null, 'first')")  # a bare heading gets a blank line
    assert r["md"].endswith("## B\n\n- first\n") and r["md"].split("\n")[r["line"]] == "- first"
    md = TREES.replace("    A --> B", "    A --> B\n    B --> C")
    r = tree_edit(lib, md, "D.insertItem(md, 'C', null, 'new tree')")
    assert r["md"].endswith("## B\n\n## C\n\n- new tree\n")
    assert tree_edit(lib, TREES, "D.insertItem(md, 'Nope', null, 'x')") is None


def test_indent_items(lib):
    r = tree_edit(lib, TREES, "D.indentItem(md, 10, 1)")  # one.b under one.a
    assert diff(TREES, r["md"]) == ["-  - one.b", "+    - one.b"]
    r = tree_edit(lib, TREES, "D.indentItem(md, 8, -1)")  # one.a and its continuation up a level
    assert diff(TREES, r["md"]) == ["-  - one.a", "-    more of one.a", "+- one.a", "+  more of one.a"]
    assert tree_edit(lib, TREES, "D.indentItem(md, 7, 1)") is None  # the first item has nothing to go under
    assert tree_edit(lib, TREES, "D.indentItem(md, 7, -1)") is None  # already a top item


def test_rename_node_in_graph_and_tree_only(lib):
    md = (
        "```mermaid\nstateDiagram-v2\n    [*] --> Open\n    Open --> Closed : Open the door\n"
        '    state "Wide open" as Open\n    Open\n```\n\n## Open\n- Open stays prose\n\n## Closed\n'
    )
    r = run(lib, "return D.renameNode(md, 'Open', 'Ajar');", md=md)
    assert diff(md, r["md"]) == [
        "-    [*] --> Open",
        "-    Open --> Closed : Open the door",
        '-    state "Wide open" as Open',
        "-    Open",
        "+    [*] --> Ajar",
        "+    Ajar --> Closed : Open the door",
        '+    state "Wide open" as Ajar',
        "+    Ajar",
        "-## Open",
        "+## Ajar",
    ]
    r = run(lib, "return D.renameNode(md, 'Busy', 'Working');", md=FLOW)
    assert diff(FLOW, r["md"]) == [
        "-  Idle[Waiting] -->|start| Busy --> Done",
        "-  Busy -.-> Idle",
        "+  Idle[Waiting] -->|start| Working --> Done",
        "+  Working -.-> Idle",
        "-- Busy",
        "+- Working",
    ]
    r = run(lib, "return D.renameNode(md, 'idle', 'rest');", md=D2)
    assert diff(D2, r["md"]) == [
        "-idle -> busy: start",
        "-busy -> idle",
        "+rest -> busy: start",
        "+busy -> rest",
        "-## idle",
        "+## rest",
    ]
    assert "error" in run(lib, "return D.renameNode(md, 'Open', 'Closed');", md=md)
    assert "error" in run(lib, "return D.renameNode(md, 'Open', 'two words');", md=md)
    assert "error" in run(lib, "return D.renameNode(md, '[*]', 'Start');", md=md)


def test_linked_new_node_is_declared_by_its_edge(lib):
    md = "```mermaid\nstateDiagram-v2\n    A --> B\n```\n\n## A\n- a\n"
    r = edit(lib, md, "r = D.addNode(m); r = D.addEdge(r.model, 'A', 'S1')")
    assert r["out"] == "```mermaid\nstateDiagram-v2\n    A --> B\n    A --> S1\n```\n\n## A\n- a\n\n## S1\n"
