import pytest

from treedit import cli
from treedit.cli import HTTPError, _ws


def test_open_svg_in_inkscape(tmp_path, monkeypatch):
    (tmp_path / "fig.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    calls = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/inkscape" if name == "inkscape" else None)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: calls.append(a))
    ws = _ws(str(tmp_path), "", [], False)
    assert ws.open_with("fig.svg") == "inkscape fig.svg"
    assert calls and calls[0][0] == ["/usr/bin/inkscape", str((tmp_path / "fig.svg").resolve())]


def test_open_refuses_other_files_and_apps(tmp_path, monkeypatch):
    (tmp_path / "fig.svg").write_text("<svg/>")
    (tmp_path / "note.md").write_text("x\n")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/inkscape")
    ws = _ws(str(tmp_path), "", [], False)
    for path, app, status in (
        ("note.md", "inkscape", 400),
        ("missing.svg", "inkscape", 404),
        ("fig.svg", "gimp", 400),
    ):
        with pytest.raises(HTTPError) as e:
            ws.open_with(path, app)
        assert e.value.status == status


def test_open_says_when_inkscape_is_missing(tmp_path, monkeypatch):
    (tmp_path / "fig.svg").write_text("<svg/>")
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(HTTPError, match="not installed"):
        _ws(str(tmp_path), "", [], False).open_with("fig.svg")
