from pathlib import Path

import pytest

from docsift.core.exceptions import EngineNotAvailableError
from docsift.core.models import EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import get_engine, register_engine, unregister_engine


class FakeEngine(ConversionEngine):
    name = "fake"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        return EngineOutput(markdown="# fake", engine_version="0.0.1")


class UnavailableEngine(FakeEngine):
    name = "ghost"

    @classmethod
    def is_available(cls) -> bool:
        return False


@pytest.fixture
def fake_engine():
    register_engine("fake", FakeEngine)
    yield
    unregister_engine("fake")


def test_get_registered_engine_returns_instance(fake_engine):
    engine = get_engine("fake")
    assert isinstance(engine, FakeEngine)
    assert engine.convert(Path("x.pdf")).markdown == "# fake"


def test_unknown_engine_raises():
    with pytest.raises(EngineNotAvailableError, match="unknown engine"):
        get_engine("nope")


def test_unavailable_engine_raises_with_install_hint():
    register_engine("ghost", UnavailableEngine)
    try:
        with pytest.raises(EngineNotAvailableError, match="docsift\\[ghost\\]"):
            get_engine("ghost")
    finally:
        unregister_engine("ghost")


def test_builtin_paths_resolve():
    from docsift.engines.docling_engine import DoclingEngine
    from docsift.engines.markitdown_engine import MarkItDownEngine
    from docsift.engines.registry import _resolve

    assert _resolve("docling") is DoclingEngine
    assert _resolve("markitdown") is MarkItDownEngine
