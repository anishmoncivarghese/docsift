from pathlib import Path

import pytest
from typer.testing import CliRunner

from docsift import __version__
from docsift.cli.main import app
from docsift.core.models import EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


class StubEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path) -> EngineOutput:
        return EngineOutput(markdown="# Stubbed", engine_version="9.9.9")


@pytest.fixture
def stub_engine():
    register_engine("markitdown", StubEngine)
    yield
    unregister_engine("markitdown")


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"docsift {__version__}" in result.output


def test_convert_help_mentions_engine_option():
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--engine" in result.output


def test_convert_writes_output(stub_engine, tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(app, ["convert", str(source), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert "document_id: doc_" in result.output
    assert (out / "note.md").exists()
    assert (out / "note.docsift.json").exists()


def test_convert_unsupported_file_exits_nonzero(tmp_path):
    source = tmp_path / "movie.mp4"
    source.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(source)])
    assert result.exit_code == 1
    assert "unsupported file type" in result.output


def test_unexpected_error_prints_type_only(monkeypatch, tmp_path):
    import docsift.services.conversion_service as svc

    def explode(path, engine="auto", output_dir=None):
        raise PermissionError("secret path details")

    monkeypatch.setattr(svc, "convert_document", explode)
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(source)])
    assert result.exit_code == 1
    assert "unexpected failure: PermissionError" in result.output
    assert "secret path details" not in result.output
    assert "Traceback" not in result.output
