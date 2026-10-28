"""The roll queue survives a reload, but not a different repository at the same path."""

import shutil
import subprocess

from treedit.queue import read, rolled

EMPTY = {"at": 0.0, "target": "", "notes": {}, "feedback": [], "history": [], "held": []}


def test_a_new_repository_at_the_same_path_starts_empty(repo):
    rolled(repo, "claude", {"pkg/a.py": "old note"}, ["1"], [{"key": "edit:pkg/a.py"}], [])
    assert read(repo)["target"] == "claude"

    shutil.rmtree(repo / ".git")
    for args in (
        ("init", "-q"),
        ("config", "user.email", "new@example.com"),
        ("config", "user.name", "new"),
        ("add", "-A"),
        ("commit", "-qm", "new case"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    assert read(repo) == EMPTY
