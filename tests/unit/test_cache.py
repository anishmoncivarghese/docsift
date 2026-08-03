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
