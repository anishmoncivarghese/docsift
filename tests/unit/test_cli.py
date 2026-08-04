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

    def convert(self, path: Path, options=None) -> EngineOutput:
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


def test_convert_writes_output(stub_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
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

    def explode(path, engine="auto", output_dir=None, options=None, use_cache=True):
        raise PermissionError("secret path details")

    monkeypatch.setattr(svc, "convert_document", explode)
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(source)])
    assert result.exit_code == 1
    assert "unexpected failure: PermissionError" in result.output
    assert "secret path details" not in result.output
    assert "Traceback" not in result.output


def test_compare_reports_both_engines_and_exits_zero(tmp_path):
    from docsift.core.exceptions import ConversionFailedError

    class OkEngine(ConversionEngine):
        name = "markitdown"

        @classmethod
        def is_available(cls) -> bool:
            return True

        def convert(self, path: Path, options=None) -> EngineOutput:
            return EngineOutput(markdown="# Hi", engine_version="1.0")

    class FailEngine(OkEngine):
        name = "docling"

        def convert(self, path: Path, options=None) -> EngineOutput:
            raise ConversionFailedError("docling failed on 'note.txt': BoomError")

    register_engine("markitdown", OkEngine)
    register_engine("docling", FailEngine)
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    out = tmp_path / "cmp"
    try:
        result = runner.invoke(app, ["compare", str(source), "--output", str(out)])
    finally:
        unregister_engine("markitdown")
        unregister_engine("docling")
    assert result.exit_code == 0, result.output
    assert "markitdown: ok" in result.output
    assert "docling: failed" in result.output
    assert (out / "note.compare.json").exists()
    assert (out / "note.compare.md").exists()


def test_convert_reports_chunks_and_accepts_chunk_flags(stub_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        ["convert", str(source), "--output", str(out), "--max-tokens", "500", "--overlap", "50"],
    )
    assert result.exit_code == 0, result.output
    assert "chunks:" in result.output


def test_convert_prints_overlap_not_supported_warning(tmp_path, monkeypatch):
    class PrechunkedEngine(ConversionEngine):
        name = "markitdown"

        @classmethod
        def is_available(cls) -> bool:
            return True

        def convert(self, path: Path, options=None) -> EngineOutput:
            from docsift.core.models import Chunk

            return EngineOutput(
                markdown="# T\n\nBody.",
                engine_version="9.9.9",
                chunks=[Chunk(chunk_id="c000", text="Body.", estimated_tokens=2)],
            )

    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    register_engine("markitdown", PrechunkedEngine)
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    try:
        result = runner.invoke(
            app,
            ["convert", str(source), "--output", str(tmp_path / "out"), "--overlap", "50"],
        )
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", StubEngine)
    assert result.exit_code == 0, result.output
    assert "warning: overlap_not_supported" in result.output


def test_convert_no_cache_flag_accepted(stub_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["convert", str(source), "--output", str(tmp_path / "o"), "--no-cache"]
    )
    assert result.exit_code == 0, result.output


def test_compare_exits_one_when_all_engines_fail(tmp_path):
    from docsift.core.exceptions import ConversionFailedError

    class FailEngine(ConversionEngine):
        name = "markitdown"

        @classmethod
        def is_available(cls) -> bool:
            return True

        def convert(self, path: Path, options=None) -> EngineOutput:
            raise ConversionFailedError("nope")

    class FailEngine2(FailEngine):
        name = "docling"

    register_engine("markitdown", FailEngine)
    register_engine("docling", FailEngine2)
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    try:
        result = runner.invoke(app, ["compare", str(source), "--output", str(tmp_path / "cmp")])
    finally:
        unregister_engine("markitdown")
        unregister_engine("docling")
    assert result.exit_code == 1
