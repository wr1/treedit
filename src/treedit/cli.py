"""
treedit - edit and annotate a directory tree in your browser.

    treedit open PATH         # open the editor (http://127.0.0.1:8765)
    treedit print PATH        # print the annotated tree (for agents, READMEs)
    treedit fb ls             # open feedback, for the agent to act on

What it does
  * Shows PATH as a tree (line/word counts, symlink targets, empty folders);
    names are coloured by document size: word count ranked among all files (folders among folders)
    (in the browser and in `treedit print` on a terminal).
  * Edit any text file; Ctrl/Cmd+S saves. Symlinked files edit their target.
  * Annotate any file or folder (including the root): your standing comments for the agent,
    which it reads but never writes. Leave feedback
    for an agent on a path, on lines of a file, or on several paths; it is open or
    done and the agent replies via `treedit fb`. Everything lives in
    PATH/.treenotes.json: a flat {"relative/path": "annotation"} map, or
    {"notes": {...}, "feedback": [...]} once there is feedback.
  * Watches the disk: when an agent (or anything else) changes the tree, the
    view refreshes. An open file reloads silently if you have no unsaved edits;
    otherwise you get a conflict banner with compare / load disk / overwrite.
  * Saves are atomic and check that the file hasn't changed since you opened it.
  * Create, rename/move and delete files and folders; notes follow renames.
    Notes whose path disappeared are listed so you can reattach or drop them.

Built on treeparse (Python 3.12+): `treedit --stub` / `-j` describe it. Binds to 127.0.0.1 by default.
"""
from __future__ import annotations

import difflib
import fnmatch
from bisect import bisect_left, bisect_right
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import ClassVar, List, Optional
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from treeparse import argument, cli, command, group, option

from . import __version__
from .term import Terminal, ws_accept

DEFAULT_IGNORE = [".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv",
                  ".DS_Store", "*.pyc", ".treedit-*", ".ruff_cache", "target"]
NOTES_NAME = ".treenotes.json"
DEFAULT_SHOW = ["notes"]  # a private notes/ repo is usually git-ignored by the project, but belongs in the tree
MAX_TEXT = 2 * 1024 * 1024  # files above this are shown but not edited


class HTTPError(Exception):
    def __init__(self, status: int, msg: str, extra: dict | None = None):
        super().__init__(msg)
        self.status, self.msg, self.extra = status, msg, extra or {}


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def decode(data: bytes):
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def count_lines(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".treedit-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            shutil.copymode(str(path), tmp)
        except OSError:
            pass
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def stamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


QUOTE_LINES = 12  # a line comment remembers (at most) this many of its lines to re-find them after edits


def locate(span: list, quote: str, text: str) -> tuple:
    """(first, last, stale): the comment's span if its quote is still there, else the nearest
    place the quote moved to, else the old span marked stale."""
    a, b = span
    have, q = text.split("\n"), quote.split("\n")
    if have[a - 1:a - 1 + len(q)] == q:
        return a, b, False
    hits = [i + 1 for i in range(len(have) - len(q) + 1) if have[i:i + len(q)] == q]
    if not hits:
        return a, b, True
    na = min(hits, key=lambda i: abs(i - a))
    return na, na + (b - a), False


def first_line(text: str) -> str:
    return (text.strip().splitlines() or [""])[0]


def fb_label(f: dict) -> str:
    """'! #3 L10-14' - how open feedback is flagged in text listings."""
    where = ""
    if f.get("lines"):
        a, b = f["lines"]
        where = f" L{a}" + (f"-{b}" if b != a else "") + (" (moved?)" if f.get("stale") else "")
    return f"! #{f['id']}{where}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


CHARS_PER_TOKEN = 4  # a rough estimate for English text and code


def skill_tokens(tree: dict) -> None:
    """In a skill tree (one holding a SKILL.md), estimate what loading costs. Files get "tok". Folders
    get "tmin" - their SKILL.md alone, no leaf loaded (a folder without one: the entry SKILL.md of each
    skill inside) - and "tmax", every text file underneath. The root gets "skills": True."""
    def has_skill(n: dict) -> bool:
        return any((c["type"] == "file" and c["name"] == "SKILL.md") or (c["type"] == "dir" and has_skill(c))
                   for c in n.get("children") or [])

    if not has_skill(tree):
        return

    def walk(n: dict, inside: bool) -> tuple:  # inside: within a skill folder
        if n["type"] != "dir":
            n["tok"] = -(-n.get("chars", 0) // CHARS_PER_TOKEN) if n.get("kind") == "text" else 0
            return 0, n["tok"]
        kids = n.get("children") or []
        entry = next((c for c in kids if c["type"] == "file" and c["name"] == "SKILL.md"), None)
        sums = [walk(c, inside or entry is not None) for c in kids]
        lo = entry["tok"] if entry else sum(a for c, (a, _) in zip(kids, sums, strict=True) if c["type"] == "dir")
        hi = sum(b for _, b in sums)
        if inside or has_skill(n):  # folders unrelated to skills keep their word count
            n["tmin"], n["tmax"] = lo, hi
        return lo, hi

    walk(tree, False)
    tree["skills"] = True


def fmt_tokens(n: int) -> str:
    return f"{n}" if n < 1000 else f"{n / 1000:.1f}k" if n < 10000 else f"{round(n / 1000)}k"


def word_totals(tree: dict) -> dict:
    """{path: words}, folders summing their children (as the web view's heat does)."""
    out: dict = {}

    def walk(n: dict) -> int:
        w = sum(walk(c) for c in n.get("children") or []) if n["type"] == "dir" else n.get("words") or 0
        out[n["path"]] = w
        return w

    walk(tree)
    return out


def dir_paths(tree: dict) -> set:
    out: set = set()

    def walk(n: dict) -> None:
        if n["type"] == "dir":
            out.add(n["path"])
            for c in n.get("children") or []:
                walk(c)

    walk(tree)
    return out


def rank_by_size(words: dict, dirs: set) -> dict:
    """{path: 0..1}: how big each document is in this tree - its word count ranked among all files
    (folders among all folders), ties sharing a rank; small sets stay near neutral (0.5)."""
    groups: dict = {}
    for path, w in words.items():
        if path and w:
            groups.setdefault(path in dirs, []).append(w)
    sizes = {k: sorted(v) for k, v in groups.items()}
    out = {"": 0.5}  # the root: default colour
    for path, w in words.items():
        ws = sizes.get(path in dirs)
        if not path or not w or not ws:
            continue
        rank = 1.0 if len(ws) == 1 else (bisect_left(ws, w) + bisect_right(ws, w) - 1) / 2 / (len(ws) - 1)
        out[path] = 0.5 + (rank - 0.5) * min(1.0, (len(ws) - 1) / 8)
    return out


HEAT_RAMP = ((0.3, 245), (0.7, None), (0.88, 214), (1.01, 196))  # size rank -> 256-colour (None = default)


def heat_ansi(rank, bold: bool) -> str:
    """ANSI start code: dim for the lower ranks of a level, default colour in the middle, amber then red
    at the top; dark grey for items without words (rank None)."""
    code = 240 if rank is None else next(c for lim, c in HEAT_RAMP if rank < lim)
    parts = (["1"] if bold else []) + ([f"38;5;{code}"] if code else [])
    return f"\033[{';'.join(parts)}m" if parts else "\033[0m"


class Workspace:
    def __init__(self, root: Path, notes_path: Path, ignore: List[str], follow_outside: bool,
                 gitignore: bool = True, show: Optional[List[str]] = None):
        self.root = root.resolve()
        self.notes_path = notes_path.resolve()
        self.ignore = ignore
        self.follow_outside = follow_outside
        self.lock = threading.RLock()
        self._info_cache: dict = {}
        self.gitignore = gitignore
        self.show = [k for k in ("/".join(self.parts(x)) for x in (show or [])) if k]
        self._git = (-1.0, frozenset())
        self.changes: dict = {}  # path -> {"at": epoch, "by": "agent" | "you"}: files that changed recently
        self._seen = None  # path -> (mtime, size) at the last scan; None until the first (baseline) scan
        self._ui = {}  # path -> when the editor itself wrote it, so that change is not the agent's
        self._texts: dict = {}  # path -> last text seen (bounded), to tell which lines a change touched
        self._text_bytes = 0
        self.line_changes: dict = {}  # path -> [{"at", "by", "ranges": [[first, last, add|chg|del], ...]}]
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "treedit"
        self.drafts_path = state / f"{hashlib.sha1(str(self.root).encode()).hexdigest()[:16]}-drafts.json"

    # ---------- paths ----------
    def ignored(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name, p) for p in self.ignore)

    def kept(self, rel: str) -> bool:
        return any(rel == k or rel.startswith(k + "/") for k in self.show)

    def git_ignored(self) -> frozenset:
        """Paths (relative to the root) that .gitignore hides, as git itself reports them, minus
        --show paths (where a nested repo's own .gitignore still applies). Cached for a second."""
        if not self.gitignore:
            return frozenset()
        at, hit = self._git
        if time.monotonic() - at < 1.0:
            return hit
        out: set = set()
        self._git_collect(self.root, "", out)
        for k in self.show:
            if (self.root / k / ".git").exists():
                self._git_collect(self.root / k, k + "/", out)
        hit = frozenset(out)
        self._git = (time.monotonic(), hit)
        return hit

    def _git_collect(self, d: Path, prefix: str, out: set) -> None:
        try:
            r = subprocess.run(["git", "-C", str(d), "ls-files", "-z", "--others", "--ignored", "--exclude-standard",
                                "--directory"], capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return
        if r.returncode != 0:  # not a git work tree, or no git
            return
        for raw in r.stdout.split(b"\0"):
            rel = prefix + os.fsdecode(raw).rstrip("/")
            if raw and not (prefix == "" and self.kept(rel)):
                out.add(rel)

    def inside(self, p: Path) -> bool:
        try:
            p.relative_to(self.root)
            return True
        except ValueError:
            return False

    @staticmethod
    def parts(rel: str) -> list[str]:
        parts = [p for p in (rel or "").replace("\\", "/").split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise HTTPError(400, "paths may not contain '..'")
        return parts

    def norm(self, rel: str) -> str:
        return "/".join(self.parts(rel))

    def node_path(self, rel: str) -> Path:
        """The directory entry itself (a symlink is not followed)."""
        parts = self.parts(rel)
        p = self.root.joinpath(*parts)
        if parts and not self.inside(p.parent.resolve()):
            raise HTTPError(403, "path is outside the root")
        return p

    def target_path(self, rel: str) -> Path:
        """Where content is read/written (symlinks followed)."""
        t = self.node_path(rel).resolve()
        if not self.follow_outside and not self.inside(t):
            raise HTTPError(403, "symlink points outside the root (start with --follow-outside to allow)")
        return t

    # ---------- scanning ----------
    TEXT_KEEP, TEXT_BUDGET = 512 * 1024, 64 * 1024 * 1024  # per file / in total, for line-change tracking

    def _by(self, rel: str) -> str:
        now = time.time()
        return "you" if any((rel == k or rel.startswith(k + "/")) and now - t < 15 for k, t in self._ui.items()) else "agent"

    def _remember_text(self, rel: str, text: str, at: float) -> None:
        old = self._texts.get(rel)
        if old is not None and old != text:
            self._line_change(rel, old, text, at)
        self._text_bytes -= len(old) if old is not None else 0
        if len(text) <= self.TEXT_KEEP and self._text_bytes + len(text) <= self.TEXT_BUDGET:
            self._texts[rel] = text
            self._text_bytes += len(text)
        else:
            self._texts.pop(rel, None)

    def _line_change(self, rel: str, old: str, new: str, at: float) -> None:
        """Record the lines (numbered in the new text) that a change added, changed or deleted, and
        carry earlier records through this change so they keep pointing at the same lines."""
        ops = difflib.SequenceMatcher(None, old.split("\n"), new.split("\n"), autojunk=False).get_opcodes()
        n_new = new.count("\n") + 1
        ranges = []
        for tag, _i1, _i2, j1, j2 in ops:
            if tag in ("replace", "insert"):
                ranges.append([j1 + 1, j2, "chg" if tag == "replace" else "add"])
            elif tag == "delete":
                k = min(j1 + 1, n_new)
                ranges.append([k, k, "del"])
        if not ranges:
            return

        def remap(line: int):  # old 1-based line -> new 1-based line, or None when it is gone
            i = line - 1
            for tag, i1, i2, j1, _j2 in ops:
                if i1 <= i < i2:
                    return j1 + (i - i1) + 1 if tag == "equal" else None
            return None

        events = []
        for ev in self.line_changes.get(rel, []):
            kept = []
            for a, b, kind in ev["ranges"]:
                moved = [m for m in (remap(x) for x in range(a, b + 1)) if m]
                if moved:
                    kept.append([min(moved), max(moved), kind])
            if kept:
                events.append({**ev, "ranges": kept})
        events.append({"at": at, "by": self._by(rel), "ranges": ranges})
        self.line_changes[rel] = [e for e in events if time.time() - e["at"] < self.CHANGE_TTL][-20:]

    def text_info(self, path: Path, st, rel: str = "") -> dict:
        key = (str(path), st.st_mtime_ns, st.st_size)
        hit = self._info_cache.get(key)
        if hit is not None:
            return hit
        if st.st_size > MAX_TEXT:
            info = {"kind": "large"}
        else:
            try:
                text = decode(path.read_bytes())
            except OSError:
                text = None
            if text is None:
                info = {"kind": "binary"}
            else:
                info = {"kind": "text", "lines": count_lines(text), "words": len(text.split()), "chars": len(text)}
                if rel:
                    with self.lock:
                        self._remember_text(rel, text.replace("\r\n", "\n"), min(time.time(), st.st_mtime))
        if len(self._info_cache) > 20000:
            self._info_cache.clear()
        self._info_cache[key] = info
        return info

    def scan(self) -> dict:
        hidden = self.git_ignored()

        def walk(d: Path, rel: str) -> list:
            out = []
            try:
                entries = list(os.scandir(d))
            except OSError:
                return out
            for e in entries:
                if self.ignored(e.name):
                    continue
                r = f"{rel}/{e.name}" if rel else e.name
                if r in hidden:
                    continue
                p = Path(e.path)
                if p == self.notes_path:
                    continue
                node: dict = {"name": e.name, "path": r}
                is_link = e.is_symlink()
                if is_link:
                    try:
                        node["link"] = os.readlink(e.path)
                    except OSError:
                        node["link"] = "?"
                try:
                    st = os.stat(e.path)
                except OSError:
                    node["type"] = "broken"
                    out.append(node)
                    continue
                if stat.S_ISDIR(st.st_mode):
                    node["type"] = "dir"
                    if is_link:
                        node["linked"] = True
                        node["children"] = []
                    else:
                        node["children"] = walk(p, r)
                else:
                    node["type"] = "file"
                    node["size"] = st.st_size
                    node["mtime"] = st.st_mtime
                    target = p.resolve()
                    if is_link and not self.follow_outside and not self.inside(target):
                        node["kind"] = "outside"
                    else:
                        node.update(self.text_info(target, st, r))
                out.append(node)
            out.sort(key=lambda n: (n["type"] != "dir", n["name"].lower()))
            return out

        tree = {"name": self.root.name, "path": "", "type": "dir", "children": walk(self.root, "")}
        skill_tokens(tree)
        self._track(tree)
        return tree

    CHANGE_TTL = 3600.0  # seconds a change is remembered (the page fades it out sooner)

    def _track(self, tree: dict) -> None:
        """Compare file mtimes/sizes with the previous scan and remember what changed, and who did it:
        writes made through the editor are "you", anything else (the agent, another editor) "agent"."""
        now, cur = time.time(), {}

        def walk(n: dict) -> None:
            for c in n.get("children") or []:
                if c["type"] == "file":
                    cur[c["path"]] = (c.get("mtime"), c.get("size"))
                walk(c)

        walk(tree)
        with self.lock:
            if self._seen is not None:
                ui = {k: t for k, t in self._ui.items() if now - t < 15}
                for path, sig in cur.items():
                    if self._seen.get(path) != sig:
                        mine = self._by(path) == "you"
                        at = min(now, sig[0] or now)  # when it happened, even if nobody was looking
                        self.changes[path] = {"at": at, "by": "you" if mine else "agent"}
                self._ui = ui
            self._seen = cur
            self.changes = {k: v for k, v in self.changes.items() if k in cur and now - v["at"] < self.CHANGE_TTL}
            self.line_changes = {k: [e for e in v if now - e["at"] < self.CHANGE_TTL]
                                 for k, v in self.line_changes.items() if k in cur}
            for k in [k for k in self._texts if k not in cur]:  # gone (or renamed): forget its text
                self._text_bytes -= len(self._texts.pop(k))

    def mark_ui(self, rel: str) -> None:
        with self.lock:
            self._ui[self.norm(rel)] = time.time()

    # ---------- drafts: unsaved edits, kept as diffs outside the project ----------
    def read_drafts(self) -> dict:
        try:
            data = json.loads(self.drafts_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def set_draft(self, rel: str, draft) -> None:
        rel = self.norm(rel)
        if not rel:
            raise HTTPError(400, "a path is required")
        with self.lock:
            drafts = self.read_drafts()
            if draft:
                drafts[rel] = {**draft, "at": time.time()}
            elif rel in drafts:
                del drafts[rel]
            else:
                return
            if drafts:
                atomic_write(self.drafts_path, (json.dumps(drafts, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
            else:
                try:
                    self.drafts_path.unlink()
                except OSError:
                    pass

    def version(self) -> str:
        """Cheap fingerprint of the tree (names, sizes, mtimes) plus the notes file."""
        h = hashlib.sha1()
        hidden = self.git_ignored()

        def walk(d: str, rel: str):
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                return
            for e in entries:
                if self.ignored(e.name) or f"{rel}/{e.name}"[1:] in hidden:
                    continue
                try:
                    st = e.stat(follow_symlinks=True)
                    sig = f"{st.st_mtime_ns}|{st.st_size}"
                except OSError:
                    sig = "broken"
                h.update(f"{rel}/{e.name}|{sig}|{e.is_symlink()}\n".encode("utf-8", "surrogateescape"))
                if e.is_dir(follow_symlinks=False):
                    walk(e.path, f"{rel}/{e.name}")

        walk(str(self.root), "")
        try:
            st = self.notes_path.stat()
            h.update(f"notes|{st.st_mtime_ns}|{st.st_size}".encode())
        except OSError:
            pass
        return h.hexdigest()[:16]

    # ---------- notes & feedback ----------
    # The store is a flat {"path": "annotation"} map, or {"notes": {...}, "feedback": [...]} once
    # feedback exists. Feedback entries: {"id", "paths", "text", "status": open|done, "reply",
    # "created", "updated"} plus "lines": [first, last] and "quote" for line comments on one file.
    def _load(self) -> dict:
        try:
            data = json.loads(self.notes_path.read_text("utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            raise HTTPError(500, f"cannot read {self.notes_path.name}: {e}") from e
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _wrapped(data: dict) -> bool:
        return isinstance(data.get("notes"), dict) or isinstance(data.get("feedback"), list)

    def read_notes(self) -> dict:
        data = self._load()
        if self._wrapped(data):
            data = data.get("notes") or {}
        return {str(k).strip("/") or ".": v for k, v in data.items() if isinstance(v, str)}

    def read_feedback(self) -> list:
        data = self._load()
        fb = data.get("feedback") if self._wrapped(data) else None
        return [f for f in fb if isinstance(f, dict) and isinstance(f.get("id"), int)] if isinstance(fb, list) else []

    def _save(self, notes: dict, feedback: list) -> None:
        clean = {k: v for k, v in sorted(notes.items()) if v.strip()}
        if not clean and not feedback and not self.notes_path.exists():
            return
        doc = {"notes": clean, "feedback": sorted(feedback, key=lambda f: f["id"])} if feedback else clean
        atomic_write(self.notes_path, (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))

    def write_notes(self, notes: dict) -> None:
        with self.lock:
            self._save(notes, self.read_feedback())

    def set_note(self, rel: str, text: str) -> None:
        key = self.norm(rel) or "."
        with self.lock:
            notes = self.read_notes()
            if text.strip():
                notes[key] = text.rstrip()
            else:
                notes.pop(key, None)
            self.write_notes(notes)

    def move_notes(self, src: str, dst: str) -> None:
        src, dst = self.norm(src) or ".", self.norm(dst) or "."

        def under(k: str) -> bool:
            return k == src or (src != "." and k.startswith(src + "/"))

        with self.lock:
            notes, feedback, moved, changed = self.read_notes(), self.read_feedback(), {}, False
            for k, v in notes.items():
                if under(k):
                    nk = dst + k[len(src):]
                    moved[nk] = (moved[nk] + "\n\n" + v) if nk in moved else v
                    changed = True
            for k in list(notes):
                if under(k):
                    del notes[k]
            for k, v in moved.items():
                notes[k] = (notes[k] + "\n\n" + v) if k in notes else v
            for f in feedback:
                new = sorted({dst + k[len(src):] if under(k) else k for k in f.get("paths", [])})
                if new != f.get("paths"):
                    f["paths"], changed = new, True
            if changed:
                self._save(notes, feedback)

    def drop_notes(self, rel: str) -> None:
        """Remove annotations under REL. Feedback is kept: it may have asked for the deletion."""
        key = self.norm(rel)
        with self.lock:
            notes = self.read_notes()
            keep = {k: v for k, v in notes.items() if not (k == key or k.startswith(key + "/"))}
            if len(keep) != len(notes):
                self.write_notes(keep)

    def add_feedback(self, paths: list, text: str, lines=None, quote: str = "") -> dict:
        keys = sorted({self.norm(p) or "." for p in paths})
        if not keys:
            raise HTTPError(400, "feedback needs at least one path")
        if not text.strip():
            raise HTTPError(400, "feedback text is empty")
        now = stamp()
        with self.lock:
            feedback = self.read_feedback()
            e = {"id": max((f["id"] for f in feedback), default=0) + 1, "paths": keys, "text": text.rstrip(),
                 "status": "open", "reply": "", "created": now, "updated": now}
            if lines:
                if len(keys) != 1:
                    raise HTTPError(400, "line comments attach to exactly one file")
                a, b = sorted(int(x) for x in lines)
                e.update(lines=[max(1, a), max(1, b)], quote=quote)
            feedback.append(e)
            self._save(self.read_notes(), feedback)
            return e

    def update_feedback(self, fid: int, **changes) -> dict:
        with self.lock:
            feedback = self.read_feedback()
            e = next((f for f in feedback if f["id"] == fid), None)
            if e is None:
                raise HTTPError(404, f"no feedback #{fid}")
            for k, v in changes.items():
                if v is None:
                    continue
                if k == "status" and v not in ("open", "done"):
                    raise HTTPError(400, "status must be open or done")
                if k in ("text", "reply", "status"):
                    e[k] = str(v).rstrip()
            e["updated"] = stamp()
            self._save(self.read_notes(), feedback)
            return e

    def delete_feedback(self, fid: int) -> None:
        with self.lock:
            feedback = self.read_feedback()
            keep = [f for f in feedback if f["id"] != fid]
            if len(keep) == len(feedback):
                raise HTTPError(404, f"no feedback #{fid}")
            self._save(self.read_notes(), keep)

    def refresh_anchors(self) -> list:
        """Follow line comments to where their quoted lines moved; persist only real changes."""
        with self.lock:
            feedback, changed = self.read_feedback(), False
            for f in feedback:
                if not f.get("lines") or not f.get("quote"):
                    continue
                try:
                    text = decode(self.target_path(f["paths"][0]).read_bytes())
                except (OSError, HTTPError):
                    text = None
                a, b, stale = locate(f["lines"], f["quote"], text) if text is not None else (*f["lines"], True)
                if [a, b] != f["lines"] or stale != bool(f.get("stale")):
                    f["lines"] = [a, b]
                    if stale:
                        f["stale"] = True
                    else:
                        f.pop("stale", None)
                    changed = True
            if changed:
                self._save(self.read_notes(), feedback)
            return feedback

    @staticmethod
    def _row_note(key: str, notes: dict, single: dict):
        parts = [notes[key]] if key in notes else []
        parts += [f"{fb_label(f)} {first_line(f['text'])}" for f in single.get(key, [])]
        return "\n".join(parts) or None

    # ---------- files ----------
    def read_file(self, rel: str) -> dict:
        rel = self.norm(rel)
        t = self.target_path(rel)
        if not t.exists():
            raise HTTPError(404, "file not found")
        if not t.is_file():
            raise HTTPError(400, "not a file")
        data = t.read_bytes()
        out = {"path": rel, "hash": sha1(data), "size": len(data)}
        if len(data) > MAX_TEXT:
            out["kind"] = "large"
            return out
        text = decode(data)
        if text is None:
            out["kind"] = "binary"
            return out
        out.update(kind="text", content=text.replace("\r\n", "\n"), crlf="\r\n" in text)
        return out

    def write_file(self, rel: str, content: str, base_hash, force: bool) -> dict:
        rel = self.norm(rel)
        if not rel:
            raise HTTPError(400, "cannot write the root")
        with self.lock:
            t = self.target_path(rel)
            old = t.read_bytes() if t.is_file() else None
            cur = sha1(old) if old is not None else None
            if not force and cur != base_hash:
                disk = self.read_file(rel) if old is not None else None
                raise HTTPError(409, "file changed on disk", {"disk": disk})
            text = content.replace("\r\n", "\n")
            if old is not None and b"\r\n" in old:
                text = text.replace("\n", "\r\n")
            data = text.encode("utf-8")
            self.mark_ui(rel)
            atomic_write(t, data)
            staged = old is None and self.git_add(rel)  # a file brought back (Restore) goes to git too
            return {"hash": sha1(data), "git": staged}

    def _git_where(self, rel: str):
        """(folder to run git in, pathspec) for REL: a file's own folder, so nested repos answer for it."""
        rel = self.norm(rel)
        p = self.node_path(rel)
        if rel and not p.is_dir():
            return p.parent, p.name
        return p, "."

    def _run_git(self, cwd: Path, *args: str, limit: int = 400_000) -> str:
        try:
            r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise HTTPError(500, f"git failed: {e}") from e
        if r.returncode != 0:
            msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
            raise HTTPError(404 if "not a git repository" in " ".join(msg) else 500, msg[0] if msg else "git failed")
        out = r.stdout[:limit].decode("utf-8", "replace")
        return out + ("\n... (cut: output too long)\n" if len(r.stdout) > limit else "")

    def git_log(self, rel: str, whole: bool, n: int) -> dict:
        """Commits touching REL (or the whole repository), newest first, plus its uncommitted changes."""
        cwd, spec = self._git_where(rel)
        top = self._run_git(cwd, "rev-parse", "--show-toplevel").strip()
        specs = [] if whole else ["--", spec]
        raw = self._run_git(cwd, "log", f"-n{max(1, min(n, 1000))}", "--format=%H%x1f%h%x1f%an%x1f%at%x1f%s%x1e", *specs)
        commits = []
        for rec in raw.split("\x1e"):
            parts = rec.strip("\n").split("\x1f")
            if len(parts) == 5:
                commits.append({"hash": parts[0], "short": parts[1], "author": parts[2], "at": int(parts[3]),
                                "subject": parts[4]})
        status = self._run_git(cwd, "status", "--short", *([] if whole else ["--", spec])).splitlines()
        return {"repo": top, "commits": commits, "status": status, "scope": "repository" if whole else (rel or ".")}

    def git_show(self, rel: str, whole: bool, commit: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{4,40}", commit or ""):
            raise HTTPError(400, "bad commit id")
        cwd, spec = self._git_where(rel)
        return self._run_git(cwd, "show", "--stat", "--patch", "--format=fuller", commit, *([] if whole else ["--", spec]))

    def git_add(self, rel: str) -> bool:
        """Stage a file the editor created, in the repository that holds it (a nested notes/ repo is its
        own); ignored paths are not forced in, and outside git nothing happens. True when staged."""
        p = self.node_path(self.norm(rel))
        try:
            r = subprocess.run(["git", "-C", str(p.parent), "add", "--", p.name], capture_output=True,
                               timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0

    def create(self, rel: str, kind: str) -> bool:
        rel = self.norm(rel)
        if not rel:
            raise HTTPError(400, "a name is required")
        p = self.node_path(rel)
        if os.path.lexists(p):
            raise HTTPError(409, f"{rel} already exists")
        self.mark_ui(rel)
        if kind == "dir":
            p.mkdir(parents=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "x", encoding="utf-8"):
                pass
            return self.git_add(rel)
        return False

    def rename(self, src: str, dst: str) -> None:
        src, dst = self.norm(src), self.norm(dst)
        if not src or not dst:
            raise HTTPError(400, "cannot move the root")
        if dst == src or dst.startswith(src + "/"):
            raise HTTPError(400, "cannot move a folder into itself")
        ps, pd = self.node_path(src), self.node_path(dst)
        if not os.path.lexists(ps):
            raise HTTPError(404, f"{src} not found")
        if os.path.lexists(pd):
            raise HTTPError(409, f"{dst} already exists")
        with self.lock:
            pd.parent.mkdir(parents=True, exist_ok=True)
            self.mark_ui(dst)
            os.rename(ps, pd)
            self.move_notes(src, dst)
            drafts = self.read_drafts()
            for k in [k for k in drafts if k == src or k.startswith(src + "/")]:
                self.set_draft(dst + k[len(src):], {x: y for x, y in drafts[k].items() if x != "at"})
                self.set_draft(k, None)

    def delete(self, rel: str) -> None:
        rel = self.norm(rel)
        if not rel:
            raise HTTPError(400, "cannot delete the root")
        p = self.node_path(rel)
        with self.lock:
            if p.is_symlink() or p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
            else:
                raise HTTPError(404, f"{rel} not found")
            self.drop_notes(rel)
            for k in [k for k in self.read_drafts() if k == rel or k.startswith(rel + "/")]:
                self.set_draft(k, None)  # deleting in the editor was confirmed, drafts included

    # ---------- export ----------
    def export(self, counts: bool = True, color: bool = False) -> str:
        tree, notes = self.scan(), self.read_notes()
        feedback = [f for f in self.refresh_anchors() if f.get("status") != "done"]
        single = {}
        for f in feedback:
            if len(f["paths"]) == 1:
                single.setdefault(f["paths"][0], []).append(f)
        rows, paths = [], {""}
        ranks = rank_by_size(word_totals(tree), dir_paths(tree))

        def label(n: dict) -> str:
            s = n["name"] + ("/" if n["type"] == "dir" else "")
            if n.get("link"):
                s += f" -> {n['link']}"
            if counts and n.get("kind") == "text":
                s += f"  {plural(n['lines'], 'line')}, {plural(n['words'], 'word')}"
                if "tok" in n:
                    s += f", ~{fmt_tokens(n['tok'])} tokens"
            elif counts and n["type"] == "dir" and n.get("tmax"):
                lo, hi = fmt_tokens(n["tmin"]), fmt_tokens(n["tmax"])
                s += f"  ~{lo} tokens" if lo == hi else f"  ~{lo}-{hi} tokens"
            elif counts and n.get("kind") in ("binary", "large"):
                s += f"  ({n['kind']}, {n['size']} bytes)"
            return s

        def paint(n: dict, text: str) -> str:
            if not color:
                return text
            return heat_ansi(ranks.get(n["path"]), n["type"] == "dir") + text + "\033[0m"

        def walk(children: list, prefix: str):
            for i, n in enumerate(children):
                paths.add(n["path"])
                last = i == len(children) - 1
                cont = prefix + ("    " if last else "│   ")
                kids = n.get("children") or []
                branch, text = prefix + ("└── " if last else "├── "), label(n)
                rows.append((branch + text, branch + paint(n, text), self._row_note(n["path"], notes, single),
                             cont + ("│" if kids else "")))
                walk(kids, cont)

        root = tree["name"] + "/"
        rows.append((root, paint(tree, root), self._row_note(".", notes, single),
                     "│" if tree["children"] else ""))
        walk(tree["children"], "")
        noted = [len(r[0]) for r in rows if r[2]]
        col = min(max(noted) + 2, 72) if noted else 0
        out = []
        for head, shown, note, cont in rows:
            if not note:
                out.append(shown)
                continue
            lines = note.strip().splitlines() or [""]
            pad = max(col, len(head) + 2)
            out.append(shown + " " * (pad - len(head)) + "# " + lines[0])
            out.extend(cont.ljust(pad) + "# " + ln for ln in lines[1:])
        if counts and tree.get("skills"):
            out += ["", f"# tokens (~{CHARS_PER_TOKEN} chars each): folder min-max = its SKILL.md alone, no leaf loaded "
                        "(a folder without one: the SKILL.md of each skill inside) - every file underneath loaded"]
        multi = [f for f in feedback if len(f["paths"]) > 1]
        if multi:
            out += ["", "# open feedback on several paths:"]
            out += [f"#   {fb_label(f)} {', '.join(f['paths'])}: {first_line(f['text'])}" for f in multi]
        orphans = sorted(k for k in notes if (k if k != "." else "") not in paths)
        if orphans:
            out += ["", "# notes on paths that no longer exist:"]
            out += [f"#   {k}: {notes[k].strip().splitlines()[0] if notes[k].strip() else ''}" for k in orphans]
        return "\n".join(out) + "\n"


def mount_names(roots: list) -> list:
    """A unique top-level name per root: its folder name, then parent/name, then a -2, -3 suffix."""
    out: list = []
    for r in roots:
        name = r.name or "root"
        if name in out:
            name = f"{r.parent.name}/{name}".replace("/", "-")
        base, i = name, 2
        while name in out:
            name, i = f"{base}-{i}", i + 1
        out.append(name)
    return out


class Mounts:
    """Several roots shown as one tree, each as a top-level folder named by mount_names(). Paths are
    "name/path/in/root"; every call goes to that root's Workspace, so each keeps its own notes file,
    gitignore, drafts and change tracking. Feedback ids become "name:N".
    The top level, and feedback on paths in several folders, go to the notes file of the folders'
    common parent (where the agent pane starts), with paths relative to it and ids "*:N"."""

    TOP = "*"

    def __init__(self, workspaces: list):
        self.mounts = dict(zip(mount_names([w.root for w in workspaces]), workspaces, strict=True))
        self.root = Path(os.path.commonpath([str(w.root) for w in workspaces]))  # where the terminal starts
        self.label = " + ".join(self.mounts)
        w0 = workspaces[0]
        same = [w for w in workspaces if w.root == self.root]  # a folder holding the others: share its notes
        self.top = same[0] if same else Workspace(self.root, self.root / NOTES_NAME, w0.ignore, w0.follow_outside,
                                                  w0.gitignore, w0.show)
        self.own_top = not same
        self.notes_path = os.pathsep.join(str(w.notes_path) for w in workspaces + ([self.top] if self.own_top else []))

    @staticmethod
    def _pre(name: str, rel: str) -> str:
        return name if rel in ("", ".") else f"{name}/{rel}"

    def split(self, rel: str):
        """(name, workspace, path inside it) for REL; a 400 for the shared top level."""
        parts = Workspace.parts(rel)
        if not parts or parts[0] not in self.mounts:
            raise HTTPError(400, "pick a path inside one of the opened folders")
        return parts[0], self.mounts[parts[0]], "/".join(parts[1:])

    def _one(self, rels: list):
        hits = {self.split(r)[0] for r in rels}
        if len(hits) != 1:
            raise HTTPError(400, "paths must be inside one opened folder")
        name = hits.pop()
        return name, self.mounts[name], [self.split(r)[2] for r in rels]

    def _to_top(self, rel: str) -> str:
        """REL in the tree as a path in the common parent's notes file ('.' = the parent itself)."""
        if not Workspace.parts(rel):
            return "."
        _, w, sub = self.split(rel)
        return w.root.joinpath(*Workspace.parts(sub)).relative_to(self.root).as_posix()

    def _from_top(self, key: str) -> str:
        if key in ("", "."):
            return ""
        p = self.root / key
        for name, w in self.mounts.items():
            if p == w.root or w.root in p.parents:
                return self._pre(name, p.relative_to(w.root).as_posix())
        return key

    def _top_out(self, f: dict) -> dict:
        if not self.own_top:
            return self._fb_out(next(n for n, w in self.mounts.items() if w is self.top), f)
        return {**f, "id": f"{self.TOP}:{f['id']}", "num": f["id"], "root": str(self.root),
                "paths": [self._from_top(p) for p in f["paths"]]}

    def _prefix_map(self, get) -> dict:
        return {self._pre(name, k): v for name, w in self.mounts.items() for k, v in get(w).items()}

    def _fid(self, fid):
        name, _, num = str(fid).rpartition(":")
        if name == self.TOP and self.own_top and num.isdigit():
            return self.top, int(num)
        if name not in self.mounts or not num.isdigit():
            raise HTTPError(404, f"no feedback #{fid}")
        return self.mounts[name], int(num)

    def _fb_out(self, name: str, f: dict) -> dict:
        return {**f, "id": f"{name}:{f['id']}", "num": f["id"], "root": str(self.mounts[name].root),
                "paths": [self._pre(name, p) for p in f["paths"]]}

    # ---------- the tree ----------
    def scan(self) -> dict:
        kids = []
        for name, w in self.mounts.items():
            t = w.scan()

            def walk(n: dict, name=name) -> None:
                n["path"] = self._pre(name, n["path"])
                for c in n.get("children") or []:
                    walk(c)

            walk(t)
            t["name"], t["mount"] = name, str(w.root)
            kids.append(t)
        return {"name": self.label, "path": "", "type": "dir", "multi": True, "children": kids}

    def version(self) -> str:
        sig = [w.version() for w in self.mounts.values()]
        if self.own_top:  # only the notes file: the parent may hold far more than the opened folders
            try:
                st = self.top.notes_path.stat()
                sig.append(f"{st.st_mtime_ns}|{st.st_size}")
            except OSError:
                pass
        return sha1("|".join(sig).encode())[:16]

    @property
    def changes(self) -> dict:
        return self._prefix_map(lambda w: w.changes)

    @property
    def line_changes(self) -> dict:
        return self._prefix_map(lambda w: w.line_changes)

    def changes_for(self, root: str):
        """(root, changes) of the opened folder at ROOT, for `treedit edits` in that folder."""
        w = next((w for w in self.mounts.values() if str(w.root) == root), None)
        return (str(w.root), w.changes) if w else (self.label, {})

    def mark_ui(self, rel: str) -> None:
        _, w, sub = self.split(rel)
        w.mark_ui(sub)

    def export(self, counts: bool = True, color: bool = False) -> str:
        out = "\n".join(w.export(counts, color) for w in self.mounts.values())
        if not self.own_top:
            return out
        note = self.top.read_notes().get(".")
        fb = [f for f in self.top.refresh_anchors() if f.get("status") != "done"]
        if note or fb:
            out += f"\n# on the opened folders together ({self.top.notes_path}):\n"
            out += "".join(f"#   {ln}\n" for ln in (note or "").strip().splitlines())
            out += "".join(f"#   {fb_label(f)} {', '.join(f['paths'])}: {first_line(f['text'])}\n" for f in fb)
        return out

    # ---------- notes & feedback ----------
    def read_notes(self) -> dict:
        top = {self._from_top(k) or ".": v for k, v in self.top.read_notes().items()} if self.own_top else {}
        return {**top, **self._prefix_map(lambda w: w.read_notes())}

    def set_note(self, rel: str, text: str) -> None:
        if not Workspace.parts(rel):
            return self.top.set_note(".", text)
        _, w, sub = self.split(rel)
        w.set_note(sub, text)

    def move_notes(self, src: str, dst: str) -> None:
        _, w, (s, d) = self._one([src, dst])
        w.move_notes(s, d)

    def refresh_anchors(self) -> list:
        out = [self._fb_out(name, f) for name, w in self.mounts.items() for f in w.refresh_anchors()]
        return out + ([self._top_out(f) for f in self.top.refresh_anchors()] if self.own_top else [])

    def add_feedback(self, paths: list, text: str, lines=None, quote: str = "") -> dict:
        if not paths:
            raise HTTPError(400, "feedback needs at least one path")
        if any(not Workspace.parts(p) for p in paths) or len({self.split(p)[0] for p in paths}) > 1:
            return self._top_out(self.top.add_feedback([self._to_top(p) for p in paths], text, lines, quote))
        name, w, subs = self._one(paths)
        return self._fb_out(name, w.add_feedback(subs, text, lines, quote))

    def update_feedback(self, fid, **changes) -> dict:
        w, num = self._fid(fid)
        if w is self.top and str(fid).startswith(self.TOP + ":"):
            return self._top_out(w.update_feedback(num, **changes))
        name = next(n for n, x in self.mounts.items() if x is w)
        return self._fb_out(name, w.update_feedback(num, **changes))

    def delete_feedback(self, fid) -> None:
        w, num = self._fid(fid)
        w.delete_feedback(num)

    # ---------- drafts ----------
    def read_drafts(self) -> dict:
        return self._prefix_map(lambda w: w.read_drafts())

    def set_draft(self, rel: str, draft) -> None:
        _, w, sub = self.split(rel)
        w.set_draft(sub, draft)

    # ---------- files ----------
    def read_file(self, rel: str) -> dict:
        name, w, sub = self.split(rel)
        return {**w.read_file(sub), "path": self._pre(name, w.norm(sub))}

    def write_file(self, rel: str, content: str, base_hash, force: bool) -> dict:
        name, w, sub = self.split(rel)
        try:
            return w.write_file(sub, content, base_hash, force)
        except HTTPError as e:
            if e.extra.get("disk"):
                e.extra["disk"]["path"] = self._pre(name, e.extra["disk"]["path"])
            raise

    def git_log(self, rel: str, whole: bool, n: int) -> dict:
        name, w, sub = self.split(rel)
        out = w.git_log(sub, whole, n)
        return {**out, "scope": out["scope"] if whole else self._pre(name, sub)}

    def git_show(self, rel: str, whole: bool, commit: str) -> str:
        _, w, sub = self.split(rel)
        return w.git_show(sub, whole, commit)

    def create(self, rel: str, kind: str) -> bool:
        _, w, sub = self.split(rel)
        return w.create(sub, kind)

    def rename(self, src: str, dst: str) -> None:
        _, w, (s, d) = self._one([src, dst])
        if not s:
            raise HTTPError(400, "an opened folder cannot be moved from treedit")
        w.rename(s, d)

    def delete(self, rel: str) -> None:
        _, w, sub = self.split(rel)
        if not sub:
            raise HTTPError(400, "an opened folder cannot be deleted from treedit")
        w.delete(sub)


class Handler(BaseHTTPRequestHandler):
    ws: Workspace
    loopback = True
    server_version = "treedit"
    token = secrets.token_urlsafe(18)  # proves a terminal connection comes from the page we served
    term = None  # Terminal, when the agent pane is available (loopback only)
    agent = ""
    context: ClassVar[dict] = {}  # what the user has selected in the window, for `treedit context`
    window = None  # the treedit-app process we launched; Ctrl+W / Ctrl+Q in the page close it
    app = False  # the page is shown in the app window (so it should handle Ctrl+W / Ctrl+Q itself)

    def log_message(self, *args):
        pass

    def send(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, obj):
        self.send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError as e:
            raise HTTPError(400, "invalid JSON") from e

    def do_GET(self):
        self.dispatch("GET")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method: str):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if self.loopback:  # guard against DNS rebinding
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
                if host not in ("127.0.0.1", "localhost", "::1"):
                    raise HTTPError(403, "bad Host header")
            if u.path.startswith("/api/") and method != "GET" and self.headers.get("X-Treedit") != "1":
                raise HTTPError(403, "missing X-Treedit header")
            self.route(method, u.path, q)
        except HTTPError as e:
            self.send_json(e.status, {"error": e.msg, **e.extra})
        except FileNotFoundError as e:
            self.send_json(404, {"error": str(e)})
        except PermissionError as e:
            self.send_json(403, {"error": str(e)})
        except ConnectionError:
            pass  # the client went away; nobody to answer
        except Exception as e:
            try:
                self.send_json(500, {"error": f"{type(e).__name__}: {e}"})
            except ConnectionError:
                pass

    def route(self, method: str, path: str, q: dict):
        ws = self.ws
        if method == "GET" and path in ("/", "/index.html"):
            cfg = json.dumps({"token": self.token, "agent": self.agent, "term": self.term is not None, "app": self.app,
                              "ptyxis": bool(shutil.which("ptyxis") or shutil.which("gnome-terminal"))})
            page = PAGE.replace("/*TREEDIT_CONFIG*/{}", cfg.replace("</", "<\\/"))
            return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if method == "GET" and path.startswith("/vendor/"):
            name = path[len("/vendor/"):]
            if name not in VENDOR:
                raise HTTPError(404, "no such file")
            return self.send(200, (resources.files(__package__) / "vendor" / name).read_bytes(), VENDOR[name])
        if method == "GET" and path == "/api/term":
            return self.terminal(q)
        if method == "GET" and path == "/api/git/log":
            return self.send_json(200, ws.git_log(q.get("path", ""), q.get("whole") == "1", int(q.get("n", "150"))))
        if method == "GET" and path == "/api/git/show":
            return self.send(200, ws.git_show(q.get("path", ""), q.get("whole") == "1", q.get("commit", "")).encode("utf-8"),
                             "text/plain; charset=utf-8")
        if method == "GET" and path == "/api/changes":
            root, changes = ws.changes_for(q.get("root", "")) if isinstance(ws, Mounts) else (str(ws.root), ws.changes)
            return self.send_json(200, {"root": root, "changes": changes, "now": time.time()})
        if method == "GET" and path == "/api/context":
            return self.send_json(200, Handler.context)
        if method == "GET" and path == "/api/version":
            return self.send_json(200, {"version": ws.version()})
        if method == "GET" and path == "/api/tree":
            v = ws.version()
            multi = isinstance(ws, Mounts)
            return self.send_json(200, {"root": ws.label if multi else ws.root.name, "rootPath": str(ws.root),
                                        "notesFile": str(ws.notes_path), "version": v,
                                        "tree": ws.scan(), "notes": ws.read_notes(),
                                        "feedback": ws.refresh_anchors(), "changes": ws.changes,
                                        "drafts": ws.read_drafts(), "lines": ws.line_changes, "now": time.time()})
        if method == "GET" and path == "/api/file":
            return self.send_json(200, ws.read_file(q.get("path", "")))
        if method == "GET" and path == "/api/export":
            return self.send(200, ws.export(q.get("counts", "1") != "0").encode("utf-8"), "text/plain; charset=utf-8")
        b = self.body()
        if method == "PUT" and path == "/api/draft":
            draft = {k: b[k] for k in ("base_hash", "diff", "full", "base") if b.get(k) is not None}
            ws.set_draft(b.get("path", ""), draft if ("diff" in draft or "full" in draft) else None)
            return self.send_json(200, {"ok": True})
        if method == "POST" and path == "/api/draft-drop":
            ws.set_draft(b.get("path", ""), None)
            return self.send_json(200, {"ok": True})
        if method == "PUT" and path == "/api/file":
            return self.send_json(200, ws.write_file(b.get("path", ""), str(b.get("content", "")),
                                                     b.get("base_hash"), bool(b.get("force"))))
        if method == "PUT" and path == "/api/note":
            ws.set_note(b.get("path", ""), str(b.get("note", "")))
            return self.send_json(200, {"ok": True})
        if method == "POST" and path == "/api/log":  # page errors, shown with TREEDIT_DEBUG=1
            if os.environ.get("TREEDIT_DEBUG"):
                print(f"page: {str(b.get('msg', ''))[:2000]}", file=sys.stderr, flush=True)
            return self.send_json(200, {"ok": True})
        if method == "POST" and path == "/api/quit":
            self.send_json(200, {"ok": True})
            if Handler.window is not None:
                Handler.window.terminate()  # open_editor() then stops the server
            else:  # headless, or the app started us: stop serving, the app follows
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            return None
        if method == "POST" and path == "/api/context":
            Handler.context = {k: b[k] for k in ("paths", "lines", "quote", "focus") if b.get(k)}
            return self.send_json(200, {"ok": True})
        if method == "POST" and path == "/api/term/external":
            return self.send_json(200, {"ok": True, "cmd": external_terminal(ws.root, self.term.env if self.term else
                                                                             dict(os.environ), self.agent)})
        if method == "POST" and path == "/api/feedback":
            return self.send_json(200, ws.add_feedback(list(b.get("paths") or []), str(b.get("text", "")),
                                                       b.get("lines"), str(b.get("quote") or "")))
        if method == "PUT" and path == "/api/feedback":
            return self.send_json(200, ws.update_feedback(self.fid(b), text=b.get("text"),
                                                          status=b.get("status"), reply=b.get("reply")))
        if method == "POST" and path == "/api/feedback-delete":
            ws.delete_feedback(self.fid(b))
            return self.send_json(200, {"ok": True})
        if method == "POST" and path == "/api/note-move":
            ws.move_notes(b.get("from", ""), b.get("to", ""))
            return self.send_json(200, {"ok": True})
        if method == "POST" and path == "/api/new":
            return self.send_json(200, {"ok": True, "git": ws.create(b.get("path", ""), b.get("kind", "file"))})
        if method == "POST" and path == "/api/rename":
            ws.rename(b.get("from", ""), b.get("to", ""))
            return self.send_json(200, {"ok": True})
        if method == "POST" and path == "/api/delete":
            ws.delete(b.get("path", ""))
            return self.send_json(200, {"ok": True})
        raise HTTPError(404, "no such endpoint")


    def fid(self, b: dict):
        """A feedback id from a request: N, or "name:N" when several folders are open."""
        return str(b.get("id", "")) if isinstance(self.ws, Mounts) else int(b.get("id", 0))

    def terminal(self, q: dict):
        """Upgrade to a WebSocket onto the shared agent terminal."""
        if self.term is None:
            raise HTTPError(404, "the agent terminal is off (it needs a loopback --host)")
        if not secrets.compare_digest(q.get("token", ""), self.token):
            raise HTTPError(403, "bad terminal token")
        if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
            raise HTTPError(403, "terminal connections must come from the treedit page")
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or "websocket" not in (self.headers.get("Upgrade") or "").lower():
            raise HTTPError(400, "expected a WebSocket upgrade")
        self.protocol_version = "HTTP/1.1"  # WebKit (the app window) rejects a 101 sent as HTTP/1.0
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", ws_accept(key))
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        try:
            self.term.serve(self.connection, self.rfile)
        except OSError:
            pass  # the page went away; never answer an upgraded socket with HTTP


def external_terminal(root: Path, env: dict, agent: str) -> str:
    """Open the agent (or a shell) in Ptyxis / GNOME Terminal. The env goes on the command line,
    because these terminals hand new windows to an already running instance."""
    shell = env.get("SHELL") or "/bin/sh"
    keep = [f"{k}={v}" for k, v in env.items() if k.startswith("TREEDIT_")]
    inner = [shell, "-ic", f"{agent}; exec {shell}"] if agent else [shell, "-i"]
    run = ["env", *keep, *inner]
    if shutil.which("ptyxis"):
        cmd = ["ptyxis", "--new-window", "--working-directory", str(root), "--", *run]
    elif shutil.which("gnome-terminal"):
        cmd = ["gnome-terminal", f"--working-directory={root}", "--", *run]
    else:
        raise HTTPError(404, "neither ptyxis nor gnome-terminal is installed")
    subprocess.Popen(cmd, cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return " ".join(cmd[:4])


VENDOR = {"xterm.js": "text/javascript; charset=utf-8", "xterm.css": "text/css; charset=utf-8",
          "addon-fit.js": "text/javascript; charset=utf-8"}
PAGE = (resources.files(__package__) / "page.html").read_text("utf-8")


def _ws(root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool = False,
        show: Optional[List[str]] = None) -> Workspace:
    r = Path(root).expanduser()
    if not r.is_dir():
        sys.exit(f"treedit: {r} is not a folder")
    n = Path(notes).expanduser() if notes else r / NOTES_NAME
    return Workspace(r, n, DEFAULT_IGNORE + list(ignore or []), follow_outside, not no_gitignore,
                     DEFAULT_SHOW if show is None else show)


def roots_of(root) -> list:
    """The folders to open, once each (a single path is fine too)."""
    return list(dict.fromkeys([root] if isinstance(root, str) else root or ["."]))


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], ConnectionError):  # a closed tab is not an error
            super().handle_error(request, client_address)


def find_app():
    """The treedit-app window: $TREEDIT_APP, else treedit-app on PATH, else the newest build in app/target."""
    env = os.environ.get("TREEDIT_APP")
    if env:
        return env if os.access(env, os.X_OK) else None
    hit = shutil.which("treedit-app")
    if hit:
        return hit
    target = Path(__file__).resolve().parents[2] / "app" / "target"
    builds = [b for b in (target / "release" / "treedit-app", target / "debug" / "treedit-app")
              if b.is_file() and os.access(b, os.X_OK)]
    return str(max(builds, key=lambda b: b.stat().st_mtime)) if builds else None


def open_editor(root: List[str], port: int, host: str, browser: bool, headless: bool, agent: str,
                notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Serve the editor on HOST:PORT (next free port if taken) and show it in the treedit-app window.
    Closing the window stops the server. Falls back to the browser when the app is not built.
    Several ROOTs open side by side, each a top-level folder of the tree with its own notes file."""
    roots = [_ws(r, notes, ignore, follow_outside, no_gitignore, show) for r in roots_of(root)]
    if notes and len(roots) > 1:
        sys.exit("treedit: --notes works with one folder; each opened folder keeps its own notes file")
    ws = roots[0] if len(roots) == 1 else Mounts(roots)
    Handler.ws = ws
    Handler.loopback = host in ("127.0.0.1", "localhost", "::1")
    srv = None
    for p in range(port, port + 20):
        try:
            srv = Server((host, p), Handler)
            break
        except OSError:
            continue
    if srv is None:
        sys.exit(f"treedit: no free port in {port}-{port + 19}")
    shown = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    url = f"http://{shown}:{srv.server_port}/"
    for w in roots:
        print(f"treedit  {w.root}\n  notes  {w.notes_path}")
    print(f"  open   {url}")
    ws.scan()  # baseline for change tracking
    agent = agent or os.environ.get("TREEDIT_AGENT", "")
    Handler.agent = agent
    if Handler.loopback:
        env = {**{k: v for k, v in os.environ.items() if k != "TREEDIT_IN_APP"}, "TERM": "xterm-256color", "COLORTERM": "truecolor", "TREEDIT_ROOT": str(roots[0].root),
               "TREEDIT_ROOTS": os.pathsep.join(str(w.root) for w in roots),
               "TREEDIT_NOTES": str(ws.notes_path), "TREEDIT_URL": url}
        Handler.term = Terminal(str(ws.root), env, agent)
        print(f"  agent  {agent or 'shell'} (right pane)")
    exe = None if headless or browser else find_app()
    Handler.app = bool(exe) or os.environ.get("TREEDIT_IN_APP") == "1"
    if exe:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        win = Handler.window = subprocess.Popen([exe, "--url", url])
        try:
            win.wait()
        except KeyboardInterrupt:
            win.terminate()
            win.wait()
        finally:
            if Handler.term:
                Handler.term.stop()
            srv.shutdown()
            srv.server_close()
        return
    if not headless and not browser:
        print("  (treedit-app not built - `make app-build` or set TREEDIT_APP; using the browser)")
    print("  (Ctrl+C to stop)")
    if not headless:
        threading.Timer(0.4, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        if Handler.term:
            Handler.term.stop()
        srv.server_close()


def print_tree(root: List[str], no_counts: bool, no_color: bool, color: bool,
               notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Print the tree with annotations and open feedback as '# ...' comments. On a terminal rows are
    coloured by document size in the tree (dim, default, amber, red; dark grey = no words)."""
    use = not no_color and (color or (sys.stdout.isatty() and not os.environ.get("NO_COLOR")))
    for i, r in enumerate(roots_of(root)):
        sys.stdout.write(("\n" if i else "") + _ws(r, notes, ignore, follow_outside, no_gitignore, show)
                         .export(counts=not no_counts, color=use))


def note_get(path: str, root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Print the user's annotation on PATH ('.' is the root); exit 1 if there is none."""
    key = "/".join(Workspace.parts(path)) or "."
    text = _ws(root, notes, ignore, follow_outside, no_gitignore, show).read_notes().get(key)
    if text is None:
        sys.exit(1)
    print(text)


def note_set(path: str, text: str, root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Set the annotation on PATH; an empty TEXT removes it. For the user: agents never write annotations."""
    _ws(root, notes, ignore, follow_outside, no_gitignore, show).set_note(path, text)


def note_mv(src: str, dst: str, root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Re-key the annotations of SRC (and everything under it) to DST, without touching files."""
    _ws(root, notes, ignore, follow_outside, no_gitignore, show).move_notes(src, dst)


def note_ls(root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """List every annotation as 'path<TAB>first line'; paths that no longer exist are marked '(gone)'."""
    ws = _ws(root, notes, ignore, follow_outside, no_gitignore, show)
    for k, v in sorted(ws.read_notes().items()):
        gone = "" if k == "." or os.path.lexists(ws.root / k) else "  (gone)"
        print(f"{k}\t{(v.strip().splitlines() or [''])[0]}{gone}")


def fb_ls(all: bool, root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """List feedback for the agent to act on: id, status, path(s), lines, the quoted code, the
    request and any reply. Open items only unless --all. Line numbers follow the quoted code."""
    items = _ws(root, notes, ignore, follow_outside, no_gitignore, show).refresh_anchors()
    for f in items:
        if f.get("status") == "done" and not all:
            continue
        print(f"{fb_label(f)[2:]}  {f.get('status', 'open')}  {', '.join(f['paths'])}")
        for ln in (f.get("quote") or "").split("\n") if f.get("quote") else []:
            print(f"    | {ln}")
        for ln in f["text"].splitlines():
            print(f"    {ln}")
        if f.get("reply"):
            print("    reply: " + "\n           ".join(f["reply"].splitlines()))
        print()


def fb_add(text: str, paths: List[str], lines: str, root: str, notes: str, ignore: List[str],
           follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Add feedback on one or more paths; --lines A-B anchors it to lines of a single file."""
    ws = _ws(root, notes, ignore, follow_outside, no_gitignore, show)
    span, quote = None, ""
    if lines:
        a, _, b = lines.partition("-")
        span = [int(a), int(b or a)]
        body = decode(ws.target_path(paths[0]).read_bytes()) or ""
        quote = "\n".join(body.split("\n")[span[0] - 1:span[0] - 1 + min(QUOTE_LINES, span[1] - span[0] + 1)])
    print(f"#{ws.add_feedback(paths, text, span, quote)['id']}")


def fb_reply(id: int, text: str, done: bool, root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Answer feedback ID (what was changed, or why not); --done also resolves it."""
    _ws(root, notes, ignore, follow_outside, no_gitignore, show).update_feedback(id, reply=text, status="done" if done else None)


def fb_done(id: int, root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Mark feedback ID done."""
    _ws(root, notes, ignore, follow_outside, no_gitignore, show).update_feedback(id, status="done")


def fb_reopen(id: int, root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Mark feedback ID open again."""
    _ws(root, notes, ignore, follow_outside, no_gitignore, show).update_feedback(id, status="open")


def fb_rm(id: int, root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool, show: List[str]) -> None:
    """Delete feedback ID."""
    _ws(root, notes, ignore, follow_outside, no_gitignore, show).delete_feedback(id)


def show_context(url: str) -> None:
    """Print what the user has selected in the treedit window: paths, and the line span with its
    quoted text when lines are selected. Inside the agent pane the window's URL is in $TREEDIT_URL."""
    base = (url or os.environ.get("TREEDIT_URL") or "http://127.0.0.1:8765/").rstrip("/")
    try:
        with urlopen(base + "/api/context", timeout=3) as r:
            ctx = json.loads(r.read())
    except (URLError, OSError, ValueError) as e:
        sys.exit(f"treedit: no treedit window at {base} ({e})")
    paths = ctx.get("paths") or []
    if not paths:
        print("nothing selected")
        return
    where = ""
    if ctx.get("lines"):
        a, b = ctx["lines"]
        where = f" L{a}" + (f"-{b}" if b != a else "")
    for p in paths:
        print(p + (where if p == (ctx.get("focus") or paths[0]) else ""))
    for ln in (ctx.get("quote") or "").split("\n") if ctx.get("quote") else []:
        print(f"    | {ln}")


def show_edits(url: str, root: str, notes: str, ignore: List[str], follow_outside: bool, no_gitignore: bool,
               show: List[str]) -> None:
    """The user's own edits, for an agent to keep apart from its work: unsaved drafts from the editor
    (shown as diffs against the file they started from) and, when the window is running, the files
    the user saved in the editor recently. Commit saved ones as the user's before your own work."""
    ws = _ws(root, notes, ignore, follow_outside, no_gitignore, show)
    now = time.time()

    def age(at) -> str:
        m = int((now - (at or now)) // 60)
        return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago"

    drafts = ws.read_drafts()
    print(f"unsaved in the editor ({len(drafts)}):" if drafts else "unsaved in the editor: none")
    for path, d in sorted(drafts.items()):
        print(f"  {path}  (draft, {age(d.get('at'))})")
        body = d.get("diff") if d.get("diff") is not None else "(file too large to diff; whole new text kept)"
        for ln in body.rstrip("\n").splitlines():
            print(f"    {ln}")
    base = (url or os.environ.get("TREEDIT_URL") or "").rstrip("/")
    if not base:
        print("saved in the editor: unknown (no treedit window; set $TREEDIT_URL or --url)")
        return
    try:
        with urlopen(f"{base}/api/changes?{urlencode({'root': str(ws.root)})}", timeout=3) as r:
            data = json.loads(r.read())
    except (URLError, OSError, ValueError):
        print(f"saved in the editor: unknown (no treedit window at {base})")
        return
    if data.get("root") != str(ws.root):
        print(f"saved in the editor: unknown (the window at {base} shows {data.get('root')})")
        return
    mine = sorted((k, v) for k, v in data.get("changes", {}).items() if v.get("by") == "you")
    print(f"saved in the editor ({len(mine)}):" if mine else "saved in the editor: none recently")
    for path, v in mine:
        print(f"  {path}  ({age(v.get('at'))})")


SKILL_HEAD = """---
name: treedit
description: Use when working in a project the user reviews with treedit (a .treenotes.json exists or $TREEDIT_ROOT is set) - read the user's annotations (`treedit annotation ls`) and open feedback (`treedit fb ls`) on files, lines and the tree structure, act on it, commit the user's edits and your own work separately with git, and on an "agent roll" pick up the user's manual edits and do light housekeeping (frontmatter, names, spelling/grammar, doubled text) (`treedit edits` shows the user's saved and unsaved edits), answer each item with `treedit fb reply ID "what changed (hash)" --done`; `treedit context` shows what the user has selected. Never write annotations.
---
"""
SKILL_WORKFLOW = """
Reviewing with the user (they see the tree, your replies and every file change live in the treedit window):
1. `treedit fb ls` - open feedback: id, path(s), line span with the quoted code, and the request.
   Run it in the tree root, or add `-C "$TREEDIT_ROOT"`. Several folders open in one window:
   `$TREEDIT_ROOTS` lists them (separated by `:`); each keeps its own annotations and feedback, so run
   `fb ls`, `edits` and `annotation ls` in each (`-C <folder>`). In the window and in `treedit context`
   their paths start with the folder's name, and feedback ids read `name:N` (`N` for the CLI).
   Feedback on the top level or on paths in several folders, and the annotation on the top level,
   live in the folders' common parent (where the pane starts): plain `treedit fb ls` there, with
   paths relative to it (ids `*:N` in the window).
2. `treedit context` - what the user has selected in the window right now (paths, lines).
3. Git keeps every diff attributable - the user's or yours - whether the user saved it or not:
   a. Before you start, and again before each commit: `git status` and `treedit edits`.
      `treedit edits` lists the user's own edits: files they saved in the editor, and unsaved drafts
      (as diffs) still open in the window.
   b. The user's saved edits that are not committed yet: commit them first, on their own, as theirs:
      `git add <their paths>` then `git commit -m "user: <what they changed>"`. Never mix them into
      your commits and never revert them.
   c. Unsaved drafts are input, not untouchable work in progress: they may be finished points the
      user never saved. When you edit a file that has a draft, read its diff (`treedit edits`) and
      merge every new point from it into your edit - keep the user's wording where you can, and
      carry over no doubled blocks. Write the result to disk yourself; don't leave a draft out
      because it is unsaved. Say in your commit and reply that the draft is included
      (`agent: <what changed>, with the user's unsaved draft (treedit #ID)`), so the user can load
      the disk version in the window and let the draft go.
   d. Your own work: one commit per feedback item, staging only the files you changed
      (`git add <path>...`, never `git add -A`):
      `git commit -m "agent: <what changed> (treedit #ID)"`.
   e. Commit in the repository that holds the file (a nested `notes/` repo is its own repository).
      Never push, amend, rebase or reset. Not a git repository? Ask the user before `git init`.
   f. After anything that merges (`git merge`, `pull`, `stash pop`, `cherry-pick`, resolving a
      conflict), read each merged file back in full, not just the diff. Merges sometimes keep both
      sides of a block that differ only slightly, leaving near-duplicate text: a paragraph, function,
      list item or heading twice with a small change. Keep the right version (usually the newer or
      fuller one), remove the other, and say in your reply what you dropped.
4. Then answer: `treedit fb reply ID "<what changed> (abc1234)" --done` with your commit's short hash.
   Not doing it, or unsure? Reply without --done and say why, or ask.
5. Annotations are the user's standing comments on files and folders (`treedit annotation ls`,
   also the `# ...` comments in `treedit print`). Read them as context and instructions. Never add,
   edit or move them: they are the user's channel to you, not a place to describe the tree.
   Answer through `treedit fb reply` instead.
Annotations and feedback live in .treenotes.json; use the CLI rather than editing that file.

Agent roll - when the user asks you to "roll" (pick up their manual edits and act on them):
1. `git status` and `treedit edits`; commit the user's saved edits as theirs first (3b).
2. Housekeeping on the files they touched, then a separate commit `agent: housekeeping (<files>)`,
   so their own diff and your tidy-up stay apart. Files with unsaved drafts: merge the draft in
   first (3c), then tidy the result.
   - Frontmatter: add or repair it where the file type expects it (a SKILL.md needs `name` and
     `description`); follow the convention of neighbouring files and invent no fields.
   - Names: when a new file or folder has a placeholder or unclear name, propose a better one in
     your reply; rename (`git mv`) only once the user agrees.
   - Language: fix spelling, grammar and punctuation in their prose with a light touch - keep their
     voice, terms and meaning. Never change code, verbatim quotes, citations or code blocks.
   - Doubled text: remove accidental duplicates - a word typed twice ("the the"), a sentence or
     paragraph pasted twice, a repeated heading, list item or frontmatter key. When two near-copies
     differ, keep the fuller one and say in your summary what you dropped.
3. Then work through `treedit fb ls` as above, and end with a short summary of what you did.

Loop roll - the same roll repeated every few minutes (in Claude Code: `/loop 3m ...`), while the user
keeps editing. Each tick picks up what changed since the last one; a quiet tick (no new edits, no open
feedback) makes no commits and answers in one line. The user ends the loop when they are done.
"""


def skill_text() -> str:
    return SKILL_HEAD + "\n" + app.stub_text().rstrip() + "\n" + SKILL_WORKFLOW


def skill_show() -> None:
    """Print the treedit agent skill (SKILL.md)."""
    sys.stdout.write(skill_text())


def skill_install(claude: bool, hermes: bool, dir: str) -> None:
    """Write SKILL.md to ~/.claude/skills/treedit and/or ~/.hermes/skills/treedit. With no flag,
    install for each agent whose home folder exists; --dir writes to DIR/treedit instead."""
    home = Path.home()
    if dir:
        targets = [Path(dir).expanduser()]
    else:
        pick = [(claude, home / ".claude"), (hermes, home / ".hermes")]
        targets = [h / "skills" for want, h in pick if want] or [h / "skills" for _, h in pick if h.is_dir()]
    if not targets:
        sys.exit("treedit: neither ~/.claude nor ~/.hermes exists; use --dir")
    for t in targets:
        atomic_write(t / "treedit" / "SKILL.md", skill_text().encode("utf-8"))
        print(t / "treedit" / "SKILL.md")


ROOT = argument(name="root", arg_type=str, nargs="*", default=["."], help="folder(s) to open")
NOTE_ROOT = option(flags=["--root", "-C"], arg_type=str, default=".", help="tree root")
SHARED = [
    option(flags=["--show"], arg_type=str, nargs="*", default=DEFAULT_SHOW,
           help="paths kept visible though .gitignore hides them"),
    option(flags=["--no-gitignore"], flag=True, help="show what .gitignore hides"),
    option(flags=["--notes"], arg_type=str, default="", help=f"notes file (empty: ROOT/{NOTES_NAME})"),
    option(flags=["--ignore"], arg_type=str, nargs="*", default=[], help="extra name globs to hide"),
    option(flags=["--follow-outside"], flag=True, help="allow symlink targets outside the root"),
]
FB_ID = argument(name="id", arg_type=int, help="feedback number (#N)")
NOTE_PATH = argument(name="path", arg_type=str, help="path relative to the root ('.' = root)")

app = cli(
    name="treedit",
    help="Review a directory tree with an agent: annotate files and folders, leave feedback (also on lines), "
         "see it coloured by word count; agents read both and answer feedback from the CLI.",
    version=__version__,
    subgroups=[
        cli(name="open", help="Open the editor window (edit files, notes, feedback, live refresh).",
            callback=open_editor, arguments=[ROOT], options=[*SHARED,
                option(flags=["--port", "-p"], arg_type=int, default=8765, help="port (next free one if taken)"),
                option(flags=["--host"], arg_type=str, default="127.0.0.1", help="interface to bind"),
                option(flags=["--browser"], flag=True, help="use the web browser instead of the app window"),
                option(flags=["--headless"], flag=True, help="only serve; open no window"),
                option(flags=["--agent", "-a"], arg_type=str, default="",
                       help="command for the right-hand pane, e.g. claude or 'hermes --skills treedit' "
                            "(default $TREEDIT_AGENT, else a shell)"),
            ]),
        cli(name="print", help="Print the annotated tree, coloured by word count per level.",
            callback=print_tree, arguments=[ROOT], options=[*SHARED,
                option(flags=["--no-counts"], flag=True, help="omit line/word counts"),
                option(flags=["--no-color"], flag=True, help="never colour"),
                option(flags=["--color"], flag=True, help="colour even when not a terminal"),
            ]),
        group(name="annotation", help="The user's comments on files and folders, for the agent to read.",
              options=[NOTE_ROOT, *SHARED],
              commands=[
                  command(name="get", help="Print one annotation.", callback=note_get, arguments=[NOTE_PATH]),
                  command(name="set", help="Set or clear one (user only).", callback=note_set,
                          arguments=[NOTE_PATH, argument(name="text", arg_type=str, help="annotation ('' clears)")]),
                  command(name="mv", help="Move annotations to a new path.", callback=note_mv,
                          arguments=[argument(name="src", arg_type=str), argument(name="dst", arg_type=str)]),
                  command(name="ls", help="List all annotations.", callback=note_ls),
              ]),
        cli(name="edits", help="The user's own edits: unsaved drafts (diffs) and files saved in the editor.",
            callback=show_edits, options=[NOTE_ROOT, *SHARED,
                                          option(flags=["--url"], arg_type=str, default="",
                                                 help="window URL (default $TREEDIT_URL)")]),
        cli(name="context", help="What the user has selected in the treedit window.", callback=show_context,
            options=[option(flags=["--url"], arg_type=str, default="", help="window URL (default $TREEDIT_URL)")]),
        group(name="skill", help="The agent skill that teaches Claude Code / Hermes to use treedit.", commands=[
            command(name="show", help="Print SKILL.md.", callback=skill_show),
            command(name="install", help="Install SKILL.md for Claude Code / Hermes.", callback=skill_install,
                    options=[option(flags=["--claude"], flag=True, help="~/.claude/skills"),
                             option(flags=["--hermes"], flag=True, help="~/.hermes/skills"),
                             option(flags=["--dir"], arg_type=str, default="", help="another skills folder")]),
        ]),
        group(name="fb", help="Feedback for the agent: list it, answer it, resolve it.", options=[NOTE_ROOT, *SHARED],
              commands=[
                  command(name="ls", help="List open feedback.", callback=fb_ls,
                          options=[option(flags=["--all", "-a"], flag=True, help="include done items")]),
                  command(name="add", help="Add feedback on paths.", callback=fb_add,
                          arguments=[argument(name="text", arg_type=str),
                                     argument(name="paths", arg_type=str, nargs="+")],
                          options=[option(flags=["--lines", "-l"], arg_type=str, default="", help="A-B (one file)")]),
                  command(name="reply", help="Reply to feedback.", callback=fb_reply,
                          arguments=[FB_ID, argument(name="text", arg_type=str)],
                          options=[option(flags=["--done", "-d"], flag=True, help="also mark it done")]),
                  command(name="done", help="Mark feedback done.", callback=fb_done, arguments=[FB_ID]),
                  command(name="reopen", help="Reopen feedback.", callback=fb_reopen, arguments=[FB_ID]),
                  command(name="rm", help="Delete feedback.", callback=fb_rm, arguments=[FB_ID]),
              ]),
    ],
)


def main(argv=None):
    if argv is not None:
        sys.argv = ["treedit", *argv]
    try:
        app.run()
    except HTTPError as e:
        sys.exit(f"treedit: {e.msg}")
    except BrokenPipeError:  # e.g. `treedit print | head`
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)


if __name__ == "__main__":
    main()
