from pathlib import Path

import pytest

from docsift.core.exceptions import EngineNotAvailableError, UnsupportedFileError
from docsift.engines.router import select_engine_name


def test_pdf_routes_to_docling():
    engine, reason = select_engine_name(Path("report.PDF"))
    assert engine == "docling"
    assert "PDF" in reason


@pytest.mark.parametrize(
    "name",
    [
        "a.docx",
        "b.pptx",
        "c.xlsx",
        "d.html",
        "e.csv",
        "f.epub",
        "g.zip",
        "h.json",
        "i.xml",
        "j.txt",
        "k.md",
    ],
)
def test_office_and_web_formats_route_to_markitdown(name):
    engine, _ = select_engine_name(Path(name))
    assert engine == "markitdown"


def test_explicit_selection_wins_over_routing():
    engine, reason = select_engine_name(Path("report.pdf"), requested="markitdown")
    assert engine == "markitdown"
    assert reason == "explicit user selection"


def test_unsupported_suffix_raises():
    with pytest.raises(UnsupportedFileError, match="unsupported file type"):
        select_engine_name(Path("movie.mp4"))


def test_unknown_engine_choice_raises():
    with pytest.raises(EngineNotAvailableError, match="unknown engine"):
        select_engine_name(Path("report.pdf"), requested="pandoc")
