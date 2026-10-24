import shutil

import pytest

from conftest import tiny_pdf

pytestmark = pytest.mark.skipif(
    not (shutil.which("pdfinfo") and shutil.which("pdftoppm")), reason="needs poppler-utils"
)


def test_pdf_info_and_page(ws, tree):
    tiny_pdf(tree / "doc.pdf")
    assert ws.pdf_info("doc.pdf")["pages"] == 1
    data, mime = ws.pdf_page("doc.pdf", 1, 96)
    assert mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n")
    assert ws.pdf_page("doc.pdf", 1, 96)[0] == data  # cached
    for bad in ("README.md", "missing.pdf", "../doc.pdf"):
        with pytest.raises(Exception):
            ws.pdf_page(bad, 1)
