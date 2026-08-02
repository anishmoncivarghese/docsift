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


def test_wrapper_strips_injected_exception_text(monkeypatch, tmp_path):
    import docling.document_converter as dc

    from docsift.core.exceptions import ConversionFailedError

    class ExplodingConverter:
        def convert(self, path):
            raise ValueError("secret document content")

    monkeypatch.setattr(dc, "DocumentConverter", ExplodingConverter)
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"%PDF-1.4")
    with pytest.raises(ConversionFailedError) as excinfo:
        DoclingEngine().convert(bad)
    message = str(excinfo.value)
    assert "secret document content" not in message
    assert "ValueError" in message


def test_convert_produces_hybrid_chunks(tmp_path):
    from docsift.core.options import ChunkOptions, ConversionOptions

    options = ConversionOptions(chunk=ChunkOptions(max_tokens=200, overlap_tokens=0))
    output = DoclingEngine().convert(FIXTURES / "multipage.pdf", options)
    assert output.chunks, "docling should produce HybridChunker chunks"
    for chunk in output.chunks:
        assert chunk.text.strip()
        assert chunk.estimated_tokens <= 200
        assert chunk.chunk_id.startswith("c")
    assert any(chunk.pages for chunk in output.chunks)


def test_markdown_contains_page_breaks_when_supported():
    output = DoclingEngine().convert(FIXTURES / "multipage.pdf")
    assert output.page_count == 3
