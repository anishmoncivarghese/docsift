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
