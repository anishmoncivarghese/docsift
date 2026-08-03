from pathlib import Path

import pytest

from docsift.core.exceptions import ConversionFailedError, UnsupportedFileError
from docsift.core.models import ConversionResult, EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine
from docsift.services.conversion_service import convert_document


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))


class EmptyEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        return EngineOutput(markdown="", engine_version="9.9.9")


class StubEngine(ConversionEngine):
    name = "markitdown"  # registered over the builtin for these tests

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        return EngineOutput(markdown="# Stubbed\n\nHello.", engine_version="9.9.9")


class ExplodingEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        raise ValueError("secret document content")


class StructuredFailureEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        raise ConversionFailedError("engine says no")


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
    assert result.document.markdown == "# Stubbed\n\nHello.\n"
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


def test_unexpected_engine_error_wraps_without_raw_exception_text(text_file):
    register_engine("markitdown", ExplodingEngine)
    try:
        with pytest.raises(ConversionFailedError) as excinfo:
            convert_document(text_file)
    finally:
        unregister_engine("markitdown")
    message = str(excinfo.value)
    assert "ValueError" in message
    assert "secret document content" not in message


def test_docsift_errors_pass_through_unwrapped(text_file):
    register_engine("markitdown", StructuredFailureEngine)
    try:
        with pytest.raises(ConversionFailedError, match="engine says no"):
            convert_document(text_file)
    finally:
        unregister_engine("markitdown")


def test_explicit_engine_does_not_bypass_extension_validation(tmp_path):
    bad = tmp_path / "movie.mp4"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFileError, match="unsupported file type"):
        convert_document(bad, engine="markitdown")


def test_empty_conversion_emits_warning(text_file):
    register_engine("markitdown", EmptyEngine)
    try:
        result = convert_document(text_file)
    finally:
        unregister_engine("markitdown")
    assert any(w.code == "empty_output" for w in result.warnings)


NOISY_MD = (
    "# Title\n\nReal paragraph one.\n\nCorp Confidential\n<!-- page-break -->\n"
    "Corp Confidential\n\nSecond paragraph.\n<!-- page-break -->\nCorp Confidential\n\n42\n"
)


class NoisyEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        return EngineOutput(markdown=NOISY_MD, engine_version="9.9.9")


class PrechunkedEngine(NoisyEngine):
    def convert(self, path: Path, options=None) -> EngineOutput:
        from docsift.core.models import Chunk

        return EngineOutput(
            markdown="# T\n\nBody.",
            engine_version="9.9.9",
            chunks=[Chunk(chunk_id="c000", text="Body.", estimated_tokens=2)],
        )


def test_pipeline_cleans_and_chunks(stub_engine, text_file):
    register_engine("markitdown", NoisyEngine)
    try:
        result = convert_document(text_file)
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", StubEngine)
    assert "Corp Confidential" not in result.document.markdown
    assert "<!-- page: 2 -->" in result.document.markdown
    assert result.metrics.raw_estimated_tokens is not None
    assert result.metrics.raw_estimated_tokens > result.metrics.estimated_tokens
    assert result.metrics.duplicate_lines_removed >= 3
    assert result.chunks
    assert result.chunks[0].chunk_id == f"{result.document_id}_c000"


def test_engine_chunks_win_over_fallback(stub_engine, text_file):
    register_engine("markitdown", PrechunkedEngine)
    try:
        result = convert_document(text_file)
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", StubEngine)
    assert len(result.chunks) == 1
    assert result.chunks[0].chunk_id == f"{result.document_id}_c000"
    # Engine-supplied chunk text now passes through clean_excerpt, which
    # normalizes with a trailing newline (see test_cleaner.py's plan-based
    # clean_excerpt contract) — this is intentional, not a regression.
    assert result.chunks[0].text == "Body.\n"


FURNISHED_MD = (
    "# Report\n\nBody paragraph one.\nACME Confidential\n<!-- page-break -->\n"
    "ACME Confidential\nBody paragraph two.\n<!-- page-break -->\n"
    "ACME Confidential\nBody paragraph three.\n"
)


class FurnishedChunkEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        from docsift.core.models import Chunk

        return EngineOutput(
            markdown=FURNISHED_MD,
            engine_version="9.9.9",
            chunks=[
                Chunk(
                    chunk_id="c000",
                    text="ACME Confidential\nBody paragraph one.",
                    estimated_tokens=99,
                ),
                Chunk(chunk_id="c001", text="ACME Confidential", estimated_tokens=99),
            ],
        )


def test_engine_chunks_are_cleaned_with_the_document_plan(stub_engine, text_file):
    register_engine("markitdown", FurnishedChunkEngine)
    try:
        result = convert_document(text_file)
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", StubEngine)
    assert result.chunks, "the body chunk must survive"
    joined = "\n".join(chunk.text for chunk in result.chunks)
    assert "ACME Confidential" not in joined
    assert "Body paragraph one." in joined


def test_chunks_emptied_by_cleaning_are_dropped(stub_engine, text_file):
    register_engine("markitdown", FurnishedChunkEngine)
    try:
        result = convert_document(text_file)
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", StubEngine)
    assert all(chunk.text.strip() for chunk in result.chunks)
    assert len(result.chunks) == 1


class AllFurnitureChunkEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        from docsift.core.models import Chunk

        return EngineOutput(
            markdown=FURNISHED_MD,
            engine_version="9.9.9",
            chunks=[Chunk(chunk_id="c000", text="ACME Confidential", estimated_tokens=99)],
        )


def test_all_chunks_empty_after_cleaning_warns(stub_engine, text_file):
    register_engine("markitdown", AllFurnitureChunkEngine)
    try:
        result = convert_document(text_file)
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", StubEngine)
    assert result.chunks == []
    assert any(w.code == "all_chunks_empty_after_cleaning" for w in result.warnings)


def test_cleaned_chunk_tokens_are_recomputed(stub_engine, text_file):
    register_engine("markitdown", FurnishedChunkEngine)
    try:
        result = convert_document(text_file)
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", StubEngine)
    assert result.chunks[0].estimated_tokens != 99
    assert result.chunks[0].estimated_tokens >= 1
