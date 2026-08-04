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
    doc = (
        FENCED + "\nBoilerplate line\n<!-- page-break -->\n"
        "Boilerplate line\n<!-- page-break -->\n"
        "Boilerplate line\n"
    )
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


def test_plan_reuse_matches_one_shot_cleaning():
    from docsift.processing.cleaner import build_clean_plan

    plan = build_clean_plan(NOISY)
    with_plan, stats_with = clean_markdown(NOISY, plan=plan)
    one_shot, stats_one = clean_markdown(NOISY)
    assert with_plan == one_shot
    assert stats_with == stats_one


def test_plan_records_detected_furniture():
    from docsift.processing.cleaner import build_clean_plan

    plan = build_clean_plan(NOISY)
    assert "ACME Corp Confidential" in plan.furniture


def test_excerpt_strips_planned_furniture_anywhere():
    from docsift.processing.cleaner import build_clean_plan, clean_excerpt

    plan = build_clean_plan(NOISY)
    excerpt = "Some body text.\nACME Corp Confidential\nMore body text.\n"
    cleaned, stats = clean_excerpt(excerpt, plan)
    assert "ACME Corp Confidential" not in cleaned
    assert "Some body text." in cleaned
    assert "More body text." in cleaned
    assert stats.furniture_lines_removed == 1


def test_excerpt_strips_page_numbers_and_image_refs():
    # Fixture is rebased onto text NOISY itself removed (via
    # CleanPlan.removed_lines) rather than an independently invented page
    # number / image ref, since clean_excerpt is now plan-driven: it may only
    # remove a line the document-level clean already removed (see FIX 1).
    # "12" and "![logo](logo.png)" are exactly the page-number and image-ref
    # lines build_clean_plan(NOISY) recorded as removed.
    from docsift.processing.cleaner import build_clean_plan, clean_excerpt

    plan = build_clean_plan(NOISY)
    cleaned, stats = clean_excerpt("Body.\n12\n![logo](logo.png)\nMore.\n", plan)
    assert "\n12\n" not in cleaned
    assert "![logo]" not in cleaned
    assert stats.page_number_lines_removed == 1
    assert stats.image_refs_removed == 1


def test_excerpt_leaves_fenced_content_alone():
    from docsift.processing.cleaner import build_clean_plan, clean_excerpt

    plan = build_clean_plan(NOISY)
    excerpt = "```\nACME Corp Confidential\n42\n```\n"
    cleaned, stats = clean_excerpt(excerpt, plan)
    assert "ACME Corp Confidential" in cleaned
    assert "42" in cleaned
    assert stats.furniture_lines_removed == 0


def test_excerpt_with_empty_plan_is_a_near_noop():
    from docsift.processing.cleaner import CleanPlan, clean_excerpt

    cleaned, stats = clean_excerpt("Alpha.\nBeta.\n", CleanPlan())
    assert cleaned == "Alpha.\nBeta.\n"
    assert stats.furniture_lines_removed == 0


def test_excerpt_keeps_furniture_text_that_also_appears_as_body():
    from docsift.processing.cleaner import build_clean_plan, clean_excerpt

    doc = "# Doc\n\n"
    for _ in range(3):
        doc += "ACME Confidential\nSome ordinary page body text here.\n<!-- page-break -->\n"
    # The mid-document occurrence below must sit well away from every page
    # boundary (start, each page break, end) or it counts as boundary-adjacent
    # itself and the intended split (furniture but not excerpt-safe) collapses.
    doc += (
        "Padding line one.\nPadding line two.\nPadding line three.\nPadding line four.\n"
        "A paragraph that legitimately says:\nACME Confidential\nand then continues.\n"
        "Padding line five.\nPadding line six.\nPadding line seven.\nPadding line eight.\n"
    )
    plan = build_clean_plan(doc)
    assert "ACME Confidential" in plan.furniture
    assert "ACME Confidential" not in plan.excerpt_furniture
    cleaned, stats = clean_excerpt("Body before.\nACME Confidential\nBody after.\n", plan)
    assert "ACME Confidential" in cleaned
    assert stats.furniture_lines_removed == 0


def test_excerpt_still_strips_boundary_only_furniture():
    from docsift.processing.cleaner import build_clean_plan, clean_excerpt

    plan = build_clean_plan(NOISY)
    assert "ACME Corp Confidential" in plan.excerpt_furniture
    cleaned, stats = clean_excerpt("Body.\nACME Corp Confidential\nMore.\n", plan)
    assert "ACME Corp Confidential" not in cleaned
    assert stats.furniture_lines_removed == 1


def test_plan_furniture_respects_remove_furniture_option():
    from docsift.core.options import CleanOptions
    from docsift.processing.cleaner import build_clean_plan

    plan = build_clean_plan(NOISY)
    assert plan.furniture
    cleaned, stats = clean_markdown(NOISY, options=CleanOptions(remove_furniture=False), plan=plan)
    assert "ACME Corp Confidential" in cleaned
    assert stats.furniture_lines_removed == 0


def test_first_page_gets_a_marker_when_pages_exist():
    cleaned, _ = clean_markdown(NOISY)
    assert cleaned.startswith("<!-- page: 1 -->")


def test_no_page_marker_when_document_has_no_page_breaks():
    cleaned, _ = clean_markdown("# Title\n\nJust one page of text.\n")
    assert "<!-- page:" not in cleaned


def test_excerpt_never_removes_lines_the_document_kept():
    from docsift.processing.cleaner import CleanPlan, clean_excerpt

    fragment = (
        "connection reset by peer\nconnection reset by peer\n"
        "        }\n        }\n0\n1\n"
    )
    cleaned, stats = clean_excerpt(fragment, CleanPlan())
    assert cleaned.count("connection reset by peer") == 2
    assert cleaned.count("        }") == 2
    assert "0" in cleaned
    assert "1" in cleaned
    assert stats.duplicate_lines_removed == 0
    assert stats.page_number_lines_removed == 0


def test_excerpt_keeps_code_lines_that_look_like_page_numbers():
    from docsift.processing.cleaner import build_clean_plan, clean_excerpt

    doc = "# Guide\n\n```\n42\n42\n```\n\nBody paragraph one.\n"
    plan = build_clean_plan(doc)
    cleaned, stats = clean_excerpt("42\n42\n", plan)
    assert cleaned.count("42") == 2
    assert stats.page_number_lines_removed == 0


def test_cleaned_document_attributes_first_page_content_to_page_one():
    from docsift.core.options import ChunkOptions
    from docsift.processing.chunker import chunk_markdown

    doc = (
        "# Report\n\nOpening paragraph on the very first page.\n"
        "<!-- page-break -->\n"
        "Second page paragraph follows here.\n"
    )
    cleaned, _ = clean_markdown(doc)
    chunks = chunk_markdown(cleaned, "doc_e2e", ChunkOptions(max_tokens=1000, overlap_tokens=0))
    assert chunks
    assert 1 in chunks[0].pages
