from pathlib import Path

import pytest

from docsift.core.exceptions import ConversionFailedError, UnsupportedFileError
from docsift.core.models import ComparisonResult, EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine
from docsift.services.comparison_service import compare_document


class GoodEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path) -> EngineOutput:
        return EngineOutput(markdown="# Title\n\n|a|b|\n|-|-|\n", engine_version="1.0.0")


class BadEngine(GoodEngine):
    name = "docling"

    def convert(self, path: Path) -> EngineOutput:
        raise ConversionFailedError("docling failed on 'note.txt': BoomError")


@pytest.fixture
def engines():
    register_engine("markitdown", GoodEngine)
    register_engine("docling", BadEngine)
    yield
    unregister_engine("markitdown")
    unregister_engine("docling")


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    file = tmp_path / "note.txt"
    file.write_text("hello world", encoding="utf-8")
    return file


def test_failure_of_one_engine_does_not_stop_comparison(engines, text_file):
    comparison = compare_document(text_file)
    assert isinstance(comparison, ComparisonResult)
    by_engine = {run.engine: run for run in comparison.runs}
    assert by_engine["markitdown"].success is True
    assert by_engine["markitdown"].heading_count == 1
    assert by_engine["markitdown"].table_count == 1
    assert by_engine["markitdown"].estimated_tokens >= 1
    assert by_engine["docling"].success is False
    assert "BoomError" in by_engine["docling"].error


def test_writes_comparison_artifacts(engines, text_file, tmp_path):
    out = tmp_path / "cmp"
    comparison = compare_document(text_file, output_dir=out)
    assert (out / "note.compare.json").exists()
    assert (out / "note.compare.md").exists()
    md_run = next(run for run in comparison.runs if run.engine == "markitdown")
    assert md_run.markdown_path is not None
    assert Path(md_run.markdown_path).exists()


def test_invalid_input_raises_before_any_engine_runs(engines, tmp_path):
    bad = tmp_path / "movie.mp4"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFileError):
        compare_document(bad)


def test_comparison_artifacts_never_contain_document_content(engines, tmp_path):
    class SecretEngine(GoodEngine):
        def convert(self, path: Path) -> EngineOutput:
            return EngineOutput(markdown="# CONFIDENTIAL-XYZ body", engine_version="1.0.0")

    register_engine("markitdown", SecretEngine)
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    out = tmp_path / "cmp"
    try:
        compare_document(source, output_dir=out)
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", GoodEngine)
    assert "CONFIDENTIAL-XYZ" in (out / "markitdown" / "note.md").read_text(encoding="utf-8")
    assert "CONFIDENTIAL-XYZ" not in (out / "note.compare.json").read_text(encoding="utf-8")
    assert "CONFIDENTIAL-XYZ" not in (out / "note.compare.md").read_text(encoding="utf-8")


def test_unexpected_failure_records_type_name_only(engines, text_file, monkeypatch):
    import docsift.services.comparison_service as cs

    def explode(path, engine="auto", output_dir=None):
        raise PermissionError("secret path details")

    monkeypatch.setattr(cs, "convert_document", explode)
    comparison = compare_document(text_file)
    for run in comparison.runs:
        assert run.success is False
        assert run.error == "PermissionError"
        assert "secret path details" not in (run.error or "")
