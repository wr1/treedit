import subprocess

import pytest

from treedit.cli import _ws


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path_factory, monkeypatch):
    """Keep drafts and skill installs out of the real home folder."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "state"))
    monkeypatch.delenv("TREEDIT_URL", raising=False)
    monkeypatch.delenv("TREEDIT_AGENT", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture
def tree(tmp_path):
    """A small project: a README, a package with two modules, a binary file and an empty folder."""
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "README.md").write_text("# proj\n\nA small project for tests.\n")
    (root / "pkg" / "a.py").write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n")
    (root / "pkg" / "b.py").write_text("x = 1\n")
    (root / "blob.bin").write_bytes(b"\0\1\2\3")
    return root


@pytest.fixture
def ws(tree):
    return _ws(str(tree), "", [], False)


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def tiny_pdf(path):
    """Write a valid one-page PDF (no dependencies), for the page rasteriser tests."""
    content = b"BT /F1 18 Tf 20 100 Td (hello) Tj ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


@pytest.fixture
def repo(tree):
    git(tree, "init", "-q")
    git(tree, "config", "user.email", "test@example.com")
    git(tree, "config", "user.name", "test")
    (tree / ".gitignore").write_text("*.log\nnotes/\n")
    (tree / "debug.log").write_text("noise\n")
    (tree / "notes").mkdir()
    (tree / "notes" / "todo.md").write_text("- x\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-qm", "init")
    return tree
