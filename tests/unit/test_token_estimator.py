import pytest

from docsift.processing.token_estimator import _estimate_fallback, estimate_tokens

tiktoken = pytest.importorskip("tiktoken")


def test_empty_text_is_zero_tokens():
    assert estimate_tokens("") == 0


def test_matches_tiktoken_o200k_exactly():
    text = "DocSift converts documents into clean, structured Markdown."
    expected = len(tiktoken.get_encoding("o200k_base").encode(text))
    assert estimate_tokens(text) == expected


def test_fallback_heuristic_unchanged():
    assert _estimate_fallback("") == 0
    assert _estimate_fallback("a" * 400) == 100
    assert _estimate_fallback("Hi") == 1
