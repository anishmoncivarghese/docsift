from pathlib import Path

import pytest

pytest.importorskip("markitdown")

from docsift.engines.markitdown_engine import MarkItDownEngine  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_is_available_when_installed():
    assert MarkItDownEngine.is_available() is True


def test_converts_html_to_markdown():
    output = MarkItDownEngine().convert(FIXTURES / "sample.html")
    assert "Hello DocSift" in output.markdown
    assert output.engine_version
