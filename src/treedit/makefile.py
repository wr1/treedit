"""The targets of a Makefile, for the tree's Make menu: read the file, do not run make.

Only plain rules are listed (`name:` or `name1 name2:`), with a `## description` from the same
line when there is one. Special targets (`.PHONY`), pattern rules (`%`), variable references and
recipe lines are left out. `.DEFAULT_GOAL` is honoured, else the first rule is the default.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_RULE = re.compile(r"^([^:]+?)\s*:(?!=)")
_GOAL = re.compile(r"^\.DEFAULT_GOAL\s*[:?+]?=\s*(\S*)")
_SKIP = set("%$=/\\*?[]{}@#:;|&<>")


def is_makefile(path: str) -> bool:
    """Makefile, GNUmakefile, or a *.mk / *.make file (not Makefile.am and friends)."""
    name = PurePosixPath(path).name.lower()
    if name in ("makefile", "gnumakefile"):
        return True
    stem, dot, ext = name.rpartition(".")
    return bool(stem) and dot == "." and ext in ("mk", "make")


def _clean(name: str) -> bool:
    return bool(name) and name[0] not in ".-|&" and not any(c in _SKIP for c in name)


def parse_targets(text: str) -> list[dict]:
    """Targets in file order: [{"name", "desc", "default"}], without duplicates."""
    logical, buf = [], ""
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        buf = f"{buf} {raw.strip()}" if buf else raw
        if buf.rstrip().endswith("\\"):
            buf = buf.rstrip()[:-1].rstrip()
            continue
        logical.append(buf)
        buf = ""
    if buf:
        logical.append(buf)

    targets: list[dict] = []
    seen: dict[str, dict] = {}
    goal = ""
    for raw in logical:
        if not raw.strip() or raw.startswith("\t") or raw.lstrip().startswith("#"):
            continue
        m = _GOAL.match(raw.strip())
        if m:
            goal = m.group(1)
            continue
        body, desc = raw, ""
        h = body.find("#")
        if h >= 0:
            if body[h : h + 2] == "##":
                desc = body[h + 2 :].strip()
            body = body[:h]
        m = _RULE.match(body.strip())
        if not m:
            continue
        for name in m.group(1).split():
            if not _clean(name):
                continue
            hit = seen.get(name)
            if hit is not None:
                if desc and not hit["desc"]:
                    hit["desc"] = desc
                continue
            seen[name] = {"name": name, "desc": desc}
            targets.append(seen[name])

    default = goal if goal in seen else (targets[0]["name"] if targets else "")
    for t in targets:
        t["default"] = t["name"] == default
    return targets
