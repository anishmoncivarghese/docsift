from pathlib import Path

import pytest

from docsift.core.exceptions import UnsupportedFileError
from docsift.core.models import ConversionResult, EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine
from docsift.services.conversion_service import convert_document


class StubEngine(ConversionEngine):
    name = "markitdown"  # registered over the builtin for these tests

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path) -> EngineOutput:
        return EngineOutput(markdown="# Stubbed\n\nHello.", engine_version="9.9.9")


@pytest.fixture
def stub_engine():
    register_engine("markitdown", StubEngine)
    yield
    unregister_engine("markitdown")


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    file = tmp_path / "note.txt"
    file.write_text("hello world", encoding="utf-8")
    return file


def test_returns_normalized_result(stub_engine, text_file):
    result = convert_document(text_file)
    assert isinstance(result, ConversionResult)
    assert result.document_id.startswith("doc_")
    assert len(result.document_id) == 4 + 12
    assert result.conversion.engine == "markitdown"
    assert result.conversion.engine_version == "9.9.9"
    assert result.conversion.selection_reason
    assert result.document.markdown == "# Stubbed\n\nHello."
    assert result.metrics.estimated_tokens >= 1
    assert result.source.sha256 == result.source.sha256.lower()
    assert len(result.source.sha256) == 64


def test_writes_markdown_and_json(stub_engine, text_file, tmp_path):
    out = tmp_path / "out"
    result = convert_document(text_file, output_dir=out)
    md = out / "note.md"
    js = out / "note.docsift.json"
    assert md.read_text(encoding="utf-8") == result.document.markdown
    assert ConversionResult.model_validate_json(js.read_text(encoding="utf-8")) == result


def test_missing_file_raises(tmp_path):
    with pytest.raises(UnsupportedFileError, match="not a file"):
        convert_document(tmp_path / "ghost.pdf")


def test_empty_file_raises(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.touch()
    with pytest.raises(UnsupportedFileError, match="empty"):
        convert_document(empty)
