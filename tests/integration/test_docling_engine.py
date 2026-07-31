from pathlib import Path

import pytest

pytest.importorskip("docling")

from docsift.engines.docling_engine import DoclingEngine  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"

pytestmark = pytest.mark.integration


def test_is_available_when_installed():
    assert DoclingEngine.is_available() is True


def test_converts_pdf_to_markdown():
    output = DoclingEngine().convert(FIXTURES / "sample.pdf")
    assert "Hello DocSift" in output.markdown
    assert output.page_count == 1
    assert output.engine_version


def test_conversion_failure_wraps_without_raw_exception_text(tmp_path):
    from docsift.core.exceptions import ConversionFailedError

    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.4 secret document content truncated garbage")
    with pytest.raises(ConversionFailedError) as excinfo:
        DoclingEngine().convert(bad)
    message = str(excinfo.value)
    assert "broken.pdf" in message
    assert "secret document content" not in message
