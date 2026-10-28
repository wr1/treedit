"""Typst files offer the compile-to-PDF button (page.html, run in node where useful)."""

import json
import shutil
import subprocess
from importlib import resources

import pytest

NODE = shutil.which("node")


def js_function(src: str, name: str) -> str:
    i = src.index(f"const {name} = ") if f"const {name} = " in src else src.index(f"function {name}(")
    end = src.index("\n", src.index(";", i))
    return src[i:end]


def test_only_typ_files_get_the_button():
    src = (resources.files("treedit") / "page.html").read_text("utf-8")
    assert '<button id="b-typst" hidden' in src
    assert "isTypst(S.file.path)" in src
    assert "'/api/typst'" in src
    if NODE is None:
        pytest.skip("needs node")
    prog = (
        js_function(src, "isTypst")
        + "\nprocess.stdout.write(JSON.stringify(['a.typ','a.TYP','a.typ.md','a.pdf'].map(isTypst)));"
    )
    got = json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)
    assert got == [True, True, False, False]
