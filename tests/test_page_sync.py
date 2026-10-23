"""The Sync dot's aggregate state (page.html, run in node)."""

import json
import shutil
import subprocess
from importlib import resources

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="needs node")


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
    return js_function(src, "syncState")


def state(lib: str, repos):
    prog = lib + f"\nprocess.stdout.write(JSON.stringify(syncState({json.dumps(repos)})));"
    return json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)


def repo(**kw):
    return {
        "branch": "main",
        "upstream": "origin/main",
        "ahead": 0,
        "behind": 0,
        "dirty": 0,
        "state": "in-sync",
        **kw,
    }


def test_nothing_to_sync(lib):
    assert state(lib, [])["state"] == "not-git"


def test_in_sync(lib):
    got = state(lib, [repo()])
    assert got["state"] == "in-sync" and "origin/main" in got["title"]


def test_local_work_is_ahead(lib):
    assert state(lib, [repo(ahead=2)])["state"] == "ahead"
    assert state(lib, [repo(dirty=1)])["state"] == "dirty"


def test_remote_work_is_behind(lib):
    got = state(lib, [repo(behind=3)])
    assert got["state"] == "behind" and "3 to pull" in got["title"]


def test_both_directions_diverge(lib):
    assert state(lib, [repo(ahead=1, behind=1)])["state"] == "diverged"
    assert state(lib, [repo(behind=1, dirty=2)])["state"] == "diverged"


def test_mounts_aggregate(lib):
    got = state(lib, [repo(behind=1), repo(dirty=2)])
    assert got["state"] == "diverged" and "1 to pull" in got["title"] and "2 uncommitted" in got["title"]


def test_no_upstream(lib):
    assert state(lib, [repo(upstream="", state="no-remote")])["state"] == "no-remote"
