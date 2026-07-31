_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Approximate token count. Heuristic (len/4) until tiktoken lands in M3."""
    if not text:
        return 0
    return max(1, round(len(text) / _CHARS_PER_TOKEN))
