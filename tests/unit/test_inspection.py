from pathlib import Path

import pytest
from typer.testing import CliRunner

from docsift.cli.main import app
from docsift.core.exceptions import UnsupportedFileError
from docsift.core.models import EngineOutput, InspectionResult
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine
from docsift.services.inspection_service import inspect_document

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


class AvailableEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    @classmethod
    def version(cls) -> str:
        return "9.9.9"

    def convert(self, path: Path, options=None) -> EngineOutput:
        raise AssertionError("inspect must never convert")


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def engine():
    register_engine("markitdown", AvailableEngine)
    yield
    unregister_engine("markitdown")


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    file = tmp_path / "note.txt"
    file.write_text("hello world", encoding="utf-8")
    return file


def test_inspect_reports_routing_without_converting(engine, text_file):
    result = inspect_document(text_file)
    assert isinstance(result, InspectionResult)
    assert result.engine == "markitdown"
    assert result.engine_available is True
    assert result.engine_version == "9.9.9"
    assert result.document_id.startswith("doc_")
    assert result.source.filename == "note.txt"
    assert result.cached is False


def test_inspect_rejects_unsupported_files(engine, tmp_path):
    bad = tmp_path / "movie.mp4"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFileError):
        inspect_document(bad)


def test_inspect_reports_unavailable_engine_without_raising(text_file):
    class MissingEngine(AvailableEngine):
        @classmethod
        def is_available(cls) -> bool:
            return False

    register_engine("markitdown", MissingEngine)
    try:
        result = inspect_document(text_file)
    finally:
        unregister_engine("markitdown")
    assert result.engine_available is False
    assert result.engine_version == "unknown"


def test_inspect_cli_prints_routing(engine, text_file):
    result = runner.invoke(app, ["inspect", str(text_file)])
    assert result.exit_code == 0, result.output
    assert "engine: markitdown" in result.output
    assert "document_id: doc_" in result.output


def test_inspect_cli_exits_one_on_bad_file(engine, tmp_path):
    bad = tmp_path / "movie.mp4"
    bad.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["inspect", str(bad)])
    assert result.exit_code == 1
