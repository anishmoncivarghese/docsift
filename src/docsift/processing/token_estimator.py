from functools import lru_cache

_CHARS_PER_TOKEN = 4
_ENCODING = "o200k_base"


def _estimate_fallback(text: str) -> int:
    """Chars/4 heuristic, used when tiktoken is unavailable."""
    if not text:
        return 0
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken
    except ImportError:
        return None
    return tiktoken.get_encoding(_ENCODING)


def estimate_tokens(text: str) -> int:
    """Token count via tiktoken o200k_base; chars/4 heuristic if tiktoken is missing."""
    if not text:
        return 0
    encoder = _encoder()
    if encoder is None:
        return _estimate_fallback(text)
    return len(encoder.encode(text))
