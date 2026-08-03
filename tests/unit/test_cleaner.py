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


NESTED_FENCE_DOC = """# Guide

```
Example showing tilde fences:
~~~
42
return 1
return 1
```

Normal text 42
"""


def test_mismatched_inner_fence_does_not_desync():
    cleaned, stats = clean_markdown(NESTED_FENCE_DOC)
    assert cleaned.count("return 1") == 2
    assert "~~~" in cleaned
    assert stats.duplicate_lines_removed == 0
    assert stats.page_number_lines_removed == 0
    assert "Normal text 42" in cleaned


def test_longer_fence_closes_only_on_matching_run():
    doc = "# T\n\n````\n```\n42\n42\n````\n\nAfter.\n"
    cleaned, stats = clean_markdown(doc)
    assert cleaned.count("42") == 2
    assert stats.duplicate_lines_removed == 0
    assert stats.page_number_lines_removed == 0


def test_repeated_body_text_without_pages_is_kept():
    doc = (
        "# Contract\n\nClause 1: The parties agree.\nNot applicable\n"
        "Clause 2: The parties agree.\nNot applicable\n"
        "Clause 3: The parties agree.\nNot applicable\n"
    )
    cleaned, stats = clean_markdown(doc)
    assert cleaned.count("Not applicable") == 3
    assert stats.furniture_lines_removed == 0


def test_mid_page_repeats_survive_when_pages_exist():
    body = "Filler line number {n} with enough words to sit mid page here.\n"
    doc = "# Doc\n\n"
    for _page in range(3):
        doc += "Header Line\n" + "".join(body.format(n=i) for i in range(6))
        doc += "Not applicable\n" + "".join(body.format(n=i + 10) for i in range(6))
        doc += "<!-- page-break -->\n"
    cleaned, stats = clean_markdown(doc)
    assert cleaned.count("Not applicable") == 3
    assert "Header Line" not in cleaned


def test_info_string_line_does_not_close_a_fence():
    doc = (
        "# Markdown Guide\n\n"
        "```\n"
        "To start a python code block, write:\n"
        "```python\n"
        "def f(): pass\n"
        "42\n"
        "42\n"
        "```\n\n"
        "Real prose after. 42\n"
    )
    cleaned, stats = clean_markdown(doc)
    assert cleaned.count("42\n42") == 1
    assert stats.page_number_lines_removed == 0
    assert stats.duplicate_lines_removed == 0
