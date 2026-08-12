from pathlib import Path

import pytest

pytest.importorskip("markitdown")

from docsift.engines.markitdown_engine import MarkItDownEngine  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_is_available_when_installed():
    assert MarkItDownEngine.is_available() is True


def test_converts_html_to_markdown():
    output = MarkItDownEngine().convert(FIXTURES / "sample.html")
    assert "Hello DocSift" in output.markdown
    assert output.engine_version


def test_conversion_failure_wraps_without_raw_exception_text(tmp_path):
    from docsift.core.exceptions import ConversionFailedError

    bad = tmp_path / "broken.docx"
    # A .docx that isn't a valid zip forces DocxConverter to raise (rather
    # than markitdown falling back to plain-text extraction), so the engine
    # actually hits the wrapping path under test.
    bad.write_bytes(b"PK\x03\x04" + b"secret document content" * 50)
    with pytest.raises(ConversionFailedError) as excinfo:
        MarkItDownEngine().convert(bad)
    message = str(excinfo.value)
    assert "broken.docx" in message
    assert "secret document content" not in message


def test_wrapper_strips_injected_exception_text(monkeypatch, tmp_path):
    import markitdown

    from docsift.core.exceptions import ConversionFailedError

    class ExplodingMarkItDown:
        def convert(self, path):
            raise ValueError("secret document content")

    monkeypatch.setattr(markitdown, "MarkItDown", ExplodingMarkItDown)
    bad = tmp_path / "x.html"
    bad.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(ConversionFailedError) as excinfo:
        MarkItDownEngine().convert(bad)
    message = str(excinfo.value)
    assert "secret document content" not in message
    assert "ValueError" in message


def test_markitdown_reports_progress_phases(tmp_path):
    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    seen = []
    MarkItDownEngine().convert(source, on_progress=seen.append)

    assert [event.phase for event in seen] == ["engine_load", "convert"]
    assert "note.csv" in seen[-1].message


def test_markitdown_converts_without_a_callback(tmp_path):
    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    assert MarkItDownEngine().convert(source).markdown


def test_slide_markers_become_page_markers():
    from docsift.engines.markitdown_engine import normalize_slide_markers

    markdown, count = normalize_slide_markers(
        "<!-- Slide number: 1 -->\n# Title\nBody\n\n<!-- Slide number: 2 -->\n# Next\n"
    )

    assert "<!-- page: 1 -->" in markdown
    assert "<!-- page: 2 -->" in markdown
    assert "Slide number" not in markdown
    assert count == 2


def test_slide_numbers_are_not_renumbered():
    """A citation must match what the user sees in PowerPoint."""
    from docsift.engines.markitdown_engine import normalize_slide_markers

    markdown, count = normalize_slide_markers(
        "<!-- Slide number: 3 -->\nA\n\n<!-- Slide number: 9 -->\nB\n"
    )

    assert "<!-- page: 3 -->" in markdown
    assert "<!-- page: 9 -->" in markdown
    assert count == 9


def test_markdown_without_slide_markers_is_untouched():
    from docsift.engines.markitdown_engine import normalize_slide_markers

    original = "# A Word document\n\nSome text.\n"
    markdown, count = normalize_slide_markers(original)

    assert markdown == original
    assert count is None


def test_convert_sets_page_count_for_a_deck(tmp_path, monkeypatch):
    import markitdown

    class FakeMarkItDown:
        def convert(self, path):
            class Result:
                text_content = (
                    "<!-- Slide number: 1 -->\n# One\n\n<!-- Slide number: 2 -->\n# Two\n"
                )
                title = None

            return Result()

    monkeypatch.setattr(markitdown, "MarkItDown", FakeMarkItDown)
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"not really a pptx")

    output = MarkItDownEngine().convert(source)

    assert output.page_count == 2
    assert "<!-- page: 2 -->" in output.markdown
