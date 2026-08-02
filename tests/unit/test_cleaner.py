from docsift.core.options import CleanOptions
from docsift.processing.cleaner import clean_markdown

NOISY = """# Annual Report

ACME Corp Confidential
<!-- page-break -->
ACME Corp Confidential

Intro paragraph.

12

![logo](logo.png)

ACME Corp Confidential
<!-- page-break -->
Repeated line.
Repeated line.

| a | b |
| a | b |

- item one
- item one

Page 3 of 3
"""


def test_furniture_removed_when_repeated_enough():
    cleaned, stats = clean_markdown(NOISY)
    assert "ACME Corp Confidential" not in cleaned
    assert stats.furniture_lines_removed == 3


def test_page_breaks_become_numbered_markers():
    cleaned, _ = clean_markdown(NOISY)
    assert "<!-- page: 2 -->" in cleaned
    assert "<!-- page: 3 -->" in cleaned
    assert "<!-- page-break -->" not in cleaned


def test_page_markers_dropped_when_disabled():
    cleaned, _ = clean_markdown(NOISY, CleanOptions(keep_page_markers=False))
    assert "<!-- page" not in cleaned


def test_page_number_lines_removed():
    cleaned, stats = clean_markdown(NOISY)
    assert "\n12\n" not in cleaned
    assert "Page 3 of 3" not in cleaned
    assert stats.page_number_lines_removed == 2


def test_image_refs_removed_by_default_kept_on_request():
    cleaned, stats = clean_markdown(NOISY)
    assert "![logo]" not in cleaned
    assert stats.image_refs_removed == 1
    kept, _ = clean_markdown(NOISY, CleanOptions(remove_image_refs=False))
    assert "![logo](logo.png)" in kept


def test_consecutive_duplicates_collapsed_but_tables_and_lists_kept():
    cleaned, stats = clean_markdown(NOISY)
    assert cleaned.count("Repeated line.") == 1
    assert cleaned.count("| a | b |") == 2
    assert cleaned.count("- item one") == 2
    assert stats.duplicate_lines_removed == 1


def test_headings_never_touched():
    cleaned, _ = clean_markdown(NOISY)
    assert "# Annual Report" in cleaned


def test_idempotent():
    once, _ = clean_markdown(NOISY)
    twice, stats = clean_markdown(once)
    assert twice == once
    assert stats.furniture_lines_removed == 0


FENCED = """# Guide

Intro text.

```python
def foo():
    return 1
    return 1
```

Some prose.

```
ERROR: retry
ERROR: retry
ERROR: retry
DONE
```

Closing text.
"""


def test_fenced_code_duplicates_survive():
    cleaned, stats = clean_markdown(FENCED)
    assert cleaned.count("return 1") == 2
    assert stats.duplicate_lines_removed == 0


def test_fenced_log_lines_are_not_furniture():
    cleaned, stats = clean_markdown(FENCED)
    assert cleaned.count("ERROR: retry") == 3
    assert stats.furniture_lines_removed == 0


def test_fenced_page_number_lines_survive():
    doc = "# T\n\n```\n42\n```\n\n42\n"
    cleaned, stats = clean_markdown(doc)
    assert "```\n42\n```" in cleaned
    assert stats.page_number_lines_removed == 1


def test_cleaning_still_works_outside_fences():
    doc = FENCED + "\nBoilerplate line\nBoilerplate line\n\nBoilerplate line\n"
    cleaned, stats = clean_markdown(doc)
    assert "Boilerplate line" not in cleaned
    assert cleaned.count("return 1") == 2
