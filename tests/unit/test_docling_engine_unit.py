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
