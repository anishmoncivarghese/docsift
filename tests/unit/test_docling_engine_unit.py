import sys
import types
from pathlib import Path

import pytest

from docsift.core.exceptions import ConversionFailedError
from docsift.engines.docling_engine import DoclingEngine


def test_wrapper_strips_injected_exception_text_without_docling(monkeypatch, tmp_path: Path):
    class ExplodingConverter:
        def convert(self, path):
            raise ValueError("secret document content")

    fake_module = types.ModuleType("docling.document_converter")
    fake_module.DocumentConverter = ExplodingConverter
    fake_package = types.ModuleType("docling")
    monkeypatch.setitem(sys.modules, "docling", fake_package)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_module)

    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"%PDF-1.4")
    with pytest.raises(ConversionFailedError) as excinfo:
        DoclingEngine().convert(bad)
    message = str(excinfo.value)
    assert "secret document content" not in message
    assert "ValueError" in message


def test_chunking_failure_degrades_to_warning(monkeypatch, tmp_path):
    import sys
    import types

    class FakeDocument:
        def export_to_markdown(self, **kwargs):
            return "# Hi\n\nBody."

        pages = {1: object()}
        texts = []

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        def convert(self, path):
            return FakeResult()

    fake_module = types.ModuleType("docling.document_converter")
    fake_module.DocumentConverter = FakeConverter
    fake_package = types.ModuleType("docling")
    monkeypatch.setitem(sys.modules, "docling", fake_package)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_module)
    monkeypatch.setitem(sys.modules, "docling_core", None)  # forces chunker ImportError

    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    output = DoclingEngine().convert(pdf)
    assert output.markdown.startswith("# Hi")
    assert output.chunks is None
    assert any(w.code == "docling_chunker_unavailable" for w in output.warnings)
