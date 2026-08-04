from pathlib import Path

import pytest

from docsift.core.models import EngineOutput
from docsift.core.options import ChunkOptions, ConversionOptions
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine
from docsift.services.conversion_service import convert_document
from docsift.storage.cache import cache_key


class CountingEngine(ConversionEngine):
    name = "markitdown"
    calls = 0

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        type(self).calls += 1
        return EngineOutput(markdown="# Cached\n\nBody.", engine_version="9.9.9")


@pytest.fixture
def counting_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    CountingEngine.calls = 0
    register_engine("markitdown", CountingEngine)
    yield CountingEngine
    unregister_engine("markitdown")


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    file = tmp_path / "note.txt"
    file.write_text("hello world", encoding="utf-8")
    return file


def test_second_conversion_hits_cache(counting_engine, text_file):
    first = convert_document(text_file)
    second = convert_document(text_file)
    assert counting_engine.calls == 1
    assert first.conversion.cached is False
    assert second.conversion.cached is True
    assert second.document.markdown == first.document.markdown


def test_no_cache_bypasses(counting_engine, text_file):
    convert_document(text_file)
    convert_document(text_file, use_cache=False)
    assert counting_engine.calls == 2


def test_option_change_is_a_cache_miss(counting_engine, text_file):
    convert_document(text_file)
    convert_document(text_file, options=ConversionOptions(chunk=ChunkOptions(max_tokens=500)))
    assert counting_engine.calls == 2


def test_cache_hit_reports_the_current_file_identity(counting_engine, tmp_path):
    first = tmp_path / "alpha.md"
    first.write_text("same bytes", encoding="utf-8")
    second = tmp_path / "beta.txt"
    second.write_text("same bytes", encoding="utf-8")
    convert_document(first, engine="markitdown")
    result = convert_document(second, engine="markitdown")
    assert result.conversion.cached is True
    assert result.source.filename == "beta.txt"


def test_cache_hit_still_writes_artifacts(counting_engine, text_file, tmp_path):
    out = tmp_path / "out"
    convert_document(text_file, output_dir=out)
    for artifact in out.iterdir():
        artifact.unlink()
    result = convert_document(text_file, output_dir=out)
    assert result.conversion.cached is True
    assert (out / "note.md").exists()
    assert (out / "note.docsift.json").exists()


def test_key_varies_with_every_component():
    base = dict(
        source_sha256="a" * 64,
        engine_name="docling",
        engine_version="2.0",
        docsift_version="0.1.0",
        options=ConversionOptions(),
    )
    key = cache_key(**base)
    assert key != cache_key(**{**base, "source_sha256": "b" * 64})
    assert key != cache_key(**{**base, "engine_name": "markitdown"})
    assert key != cache_key(**{**base, "engine_version": "2.1"})
    assert key != cache_key(**{**base, "docsift_version": "0.2.0"})
    assert key != cache_key(
        **{**base, "options": ConversionOptions(chunk=ChunkOptions(max_tokens=99))}
    )


def test_cache_stats_and_clear(counting_engine, text_file):
    from docsift.storage.cache import cache_stats, clear_cache

    convert_document(text_file)
    count, size = cache_stats()
    assert count == 1
    assert size > 0
    assert clear_cache() == 1
    assert cache_stats() == (0, 0)


def test_cache_cli_info_and_clear(counting_engine, text_file):
    from typer.testing import CliRunner

    from docsift.cli.main import app

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    convert_document(text_file)
    info = runner.invoke(app, ["cache", "info"])
    assert info.exit_code == 0, info.output
    assert "entries: 1" in info.output
    cleared = runner.invoke(app, ["cache", "clear"])
    assert cleared.exit_code == 0, cleared.output
    assert "removed 1" in cleared.output


def test_artifact_collision_is_warned(counting_engine, tmp_path):
    first = tmp_path / "a" / "report.txt"
    first.parent.mkdir()
    first.write_text("first document", encoding="utf-8")
    second = tmp_path / "b" / "report.txt"
    second.parent.mkdir()
    second.write_text("a different document", encoding="utf-8")
    out = tmp_path / "out"
    convert_document(first, output_dir=out)
    result = convert_document(second, output_dir=out)
    assert any(w.code == "artifact_overwritten" for w in result.warnings)


def test_clear_cache_ignores_files_docsift_did_not_write(counting_engine, text_file, tmp_path):
    from docsift.storage.cache import cache_dir, cache_stats, clear_cache

    convert_document(text_file)
    stranger = cache_dir() / "package-lock.json"
    stranger.write_text("{}", encoding="utf-8")
    assert cache_stats()[0] == 1
    assert clear_cache() == 1
    assert stranger.exists()


def test_clear_cache_ignores_a_newline_suffixed_entry_name(counting_engine, text_file):
    from docsift.storage.cache import _ENTRY_NAME, cache_dir, cache_stats, clear_cache

    # The regex is the guard that matters: `$` would accept a trailing newline,
    # `fullmatch` does not. Asserted directly because the end-to-end path below
    # cannot reach it — `cache_entries()` globs `*.json` first, and glob already
    # excludes a name ending in `.json\n`, so the on-disk case passes either way.
    assert _ENTRY_NAME.fullmatch("f" * 64 + ".json") is not None
    assert _ENTRY_NAME.fullmatch("f" * 64 + ".json\n") is None

    convert_document(text_file)
    stranger = cache_dir() / ("f" * 64 + ".json\n")
    stranger.write_text("{}", encoding="utf-8")
    assert cache_stats()[0] == 1
    assert clear_cache() == 1
    assert stranger.exists()


def test_cache_info_on_fresh_machine_is_read_only(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from docsift.cli.main import app

    fresh_dir = tmp_path / "never-created-cache"
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(fresh_dir))
    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    info = runner.invoke(app, ["cache", "info"])
    assert info.exit_code == 0, info.output
    assert "entries: 0" in info.output
    assert not fresh_dir.exists()


def test_cache_stats_survives_entries_vanishing(counting_engine, text_file, monkeypatch):
    from pathlib import Path

    from docsift.storage import cache as cache_module

    convert_document(text_file)
    real_entries = cache_module.cache_entries()

    def entries_with_a_ghost() -> list[Path]:
        return [*real_entries, real_entries[0].with_name("f" * 64 + ".json")]

    monkeypatch.setattr(cache_module, "cache_entries", entries_with_a_ghost)
    count, size = cache_module.cache_stats()
    assert count == 1
    assert size > 0
