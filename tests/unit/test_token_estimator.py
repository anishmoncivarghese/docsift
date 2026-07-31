from docsift.processing.token_estimator import estimate_tokens


def test_empty_text_is_zero_tokens():
    assert estimate_tokens("") == 0


def test_four_chars_per_token_heuristic():
    assert estimate_tokens("a" * 400) == 100


def test_short_text_is_at_least_one_token():
    assert estimate_tokens("Hi") == 1
