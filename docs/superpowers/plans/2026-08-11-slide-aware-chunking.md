# Slide-Aware Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PowerPoint chunks carry their slide number and slide title, by normalising MarkItDown's slide markers into the page-marker convention the pipeline already understands.

**Architecture:** `MarkItDownEngine` rewrites `<!-- Slide number: N -->` to `<!-- page: N -->` and sets `page_count`. The cleaner and chunker are already built for that marker; the chunker is not modified at all. One rewrite fixes three symptoms: missing `pages`, empty `section_path`, and marker text leaking into chunks.

**Tech Stack:** Python 3.11+, pydantic, pytest, python-pptx (already present via `markitdown[pptx]`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-slide-aware-chunking-design.md`.
- **Do not modify `src/docsift/processing/chunker.py`.** If a task seems to need it, the design is wrong — stop and ask.
- Engine-specific formats stay inside `engines/` (CLAUDE.md rule 4).
- Slide numbers are used exactly as MarkItDown reports them; never renumbered.
- A deck with no markers must convert without attribution and without raising.
- Engine imports stay lazy (CLAUDE.md rule 1).
- Conventional commits; TDD — failing test first.

---

### Task 1: Rewrite slide markers in the MarkItDown engine

**Files:**
- Modify: `src/docsift/engines/markitdown_engine.py`
- Test: `tests/unit/test_markitdown_engine.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: module-level `normalize_slide_markers(markdown: str) -> tuple[str, int | None]` returning the rewritten Markdown and the highest slide number seen (or `None` when there were no markers). `MarkItDownEngine.convert` returns `EngineOutput` with the rewritten markdown and `page_count` set from it.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_markitdown_engine.py
def test_slide_markers_become_page_markers():
    from docsift.engines.markitdown_engine import normalize_slide_markers

    markdown, count = normalize_slide_markers(
        "<!-- Slide number: 1 -->\n# Title\nBody\n\n<!-- Slide number: 2 -->\n# Next\n"
    )

    assert "<!-- page: 1 -->" in markdown
    assert "<!-- page: 2 -->" in markdown
    assert "Slide number" not in markdown
    assert count == 2


def test_slide_numbers_are_not_renumbered():
    """A citation must match what the user sees in PowerPoint."""
    from docsift.engines.markitdown_engine import normalize_slide_markers

    markdown, count = normalize_slide_markers(
        "<!-- Slide number: 3 -->\nA\n\n<!-- Slide number: 9 -->\nB\n"
    )

    assert "<!-- page: 3 -->" in markdown
    assert "<!-- page: 9 -->" in markdown
    assert count == 9


def test_markdown_without_slide_markers_is_untouched():
    from docsift.engines.markitdown_engine import normalize_slide_markers

    original = "# A Word document\n\nSome text.\n"
    markdown, count = normalize_slide_markers(original)

    assert markdown == original
    assert count is None


def test_convert_sets_page_count_for_a_deck(tmp_path, monkeypatch):
    import markitdown

    from docsift.engines.markitdown_engine import MarkItDownEngine

    class FakeMarkItDown:
        def convert(self, path):
            class Result:
                text_content = "<!-- Slide number: 1 -->\n# One\n\n<!-- Slide number: 2 -->\n# Two\n"
                title = None

            return Result()

    monkeypatch.setattr(markitdown, "MarkItDown", FakeMarkItDown)
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"not really a pptx")

    output = MarkItDownEngine().convert(source)

    assert output.page_count == 2
    assert "<!-- page: 2 -->" in output.markdown
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_markitdown_engine.py -k slide -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_slide_markers'`

- [ ] **Step 3: Write minimal implementation**

Add near the top of `src/docsift/engines/markitdown_engine.py` (with `import re`):

```python
# MarkItDown marks slide boundaries its own way. The rest of the pipeline --
# the cleaner's furniture detection, the chunker's page attribution -- is built
# around `<!-- page: N -->`, so translate here, at the engine boundary, rather
# than teaching those modules a second vendor's format.
_SLIDE_MARKER = re.compile(r"^<!-- Slide number: (\d+) -->$", re.MULTILINE)


def normalize_slide_markers(markdown: str) -> tuple[str, int | None]:
    """Rewrite slide markers as page markers; return that and the slide count.

    Numbers are carried across untouched: a citation should match what the user
    sees in PowerPoint, not a recount. Returns None for the count when the
    document has no slide markers at all, which is every non-presentation
    format and any deck an older MarkItDown produced.
    """
    numbers = [int(match.group(1)) for match in _SLIDE_MARKER.finditer(markdown)]
    if not numbers:
        return markdown, None
    return _SLIDE_MARKER.sub(r"<!-- page: \1 -->", markdown), max(numbers)
```

Then in `convert`, replace the return:

```python
        markdown, page_count = normalize_slide_markers(result.text_content or "")
        return EngineOutput(
            markdown=markdown,
            title=getattr(result, "title", None),
            page_count=page_count,
            engine_version=metadata.version("markitdown"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_markitdown_engine.py -v`
Expected: PASS, no regressions

- [ ] **Step 5: Commit**

```bash
git add src/docsift/engines/markitdown_engine.py tests/unit/test_markitdown_engine.py
git commit -m "feat: give PowerPoint slides the page-marker treatment"
```

---

### Task 2: Strip engine-supplied markers when they are not wanted

`keep_page_markers=False` currently only stops the cleaner *inserting* markers.
Task 1 makes an engine emit them, so without this a PDF would honour the option
and a deck would not.

**Files:**
- Modify: `src/docsift/processing/cleaner.py:125-137` (the numbering loop)
- Test: `tests/unit/test_cleaner.py`

**Interfaces:**
- Consumes: `CleanOptions.keep_page_markers` (default `True`, `core/options.py:6`).
- Produces: no signature change.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_cleaner.py
def test_engine_supplied_page_markers_are_dropped_when_not_wanted():
    """A marker the engine put there must obey the same option as one we add."""
    from docsift.core.options import CleanOptions
    from docsift.processing.cleaner import clean_markdown

    markdown = "<!-- page: 1 -->\n# One\n\n<!-- page: 2 -->\n# Two\n"
    cleaned, _ = clean_markdown(markdown, CleanOptions(keep_page_markers=False))

    assert "<!-- page:" not in cleaned
    assert "# One" in cleaned
    assert "# Two" in cleaned


def test_engine_supplied_page_markers_are_kept_by_default():
    from docsift.core.options import CleanOptions
    from docsift.processing.cleaner import clean_markdown

    markdown = "<!-- page: 1 -->\n# One\n"
    cleaned, _ = clean_markdown(markdown, CleanOptions())

    assert "<!-- page: 1 -->" in cleaned
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_cleaner.py -k page_markers -v`
Expected: FAIL — the first test finds `<!-- page:` still present.

- [ ] **Step 3: Write minimal implementation**

In the numbering loop in `clean_markdown`, alongside the existing `PAGE_BREAK`
branch, drop markers that were already in the text when the option is off:

```python
        if not fenced and _PAGE_MARKER.match(line.strip()) and not options.keep_page_markers:
            # An engine can supply these itself (MarkItDown does, for slides).
            # Honour the option regardless of who wrote the marker.
            continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cleaner.py -v`
Expected: PASS, no regressions

- [ ] **Step 5: Commit**

```bash
git add src/docsift/processing/cleaner.py tests/unit/test_cleaner.py
git commit -m "fix: honour keep_page_markers for engine-supplied markers"
```

---

### Task 3: A real deck fixture, and attribution proven end to end

Unit tests on a regex prove the rewrite. Only a real conversion proves a chunk
comes back saying "slide 14" — which is the actual goal.

**Files:**
- Create: `tests/fixtures/make_deck.py`
- Create: `tests/fixtures/deck.pptx` (generated, committed)
- Test: `tests/unit/test_slide_attribution.py`

**Interfaces:**
- Consumes: `normalize_slide_markers` (Task 1) via the full pipeline.
- Produces: nothing importable.

- [ ] **Step 1: Write the fixture generator and generate it**

```python
# tests/fixtures/make_deck.py
"""Regenerate `deck.pptx`, the fixture that proves slide attribution.

Run with `uv run python tests/fixtures/make_deck.py`. The output is committed;
this exists so the fixture can be explained and rebuilt.

60 slides because the point of retrieval is a deck too long to read whole, and
because a one-slide deck would pass an attribution test by accident.
"""

from pathlib import Path

from pptx import Presentation

HERE = Path(__file__).parent
SLIDE_COUNT = 60
# Only slide 14 mentions this. A search for it must come back citing 14.
NEEDLE = "Vendor dependency remains unresolved in the APAC corridor"


def main() -> None:
    prs = Presentation()
    for number in range(1, SLIDE_COUNT + 1):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = f"Section {number}"
        body = slide.placeholders[1].text_frame
        body.text = NEEDLE if number == 14 else f"Routine content for slide {number}."
        body.add_paragraph().text = f"Owner: team {number % 7}"
    prs.save(HERE / "deck.pptx")
    print("wrote", HERE / "deck.pptx")


if __name__ == "__main__":
    main()
```

Run: `uv run python tests/fixtures/make_deck.py`
Expected: `wrote .../tests/fixtures/deck.pptx`

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_slide_attribution.py
"""What a chunk from a deck can actually be cited as."""

from pathlib import Path

import pytest

pytest.importorskip("markitdown")

from docsift.services.conversion_service import convert_document  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"
NEEDLE = "Vendor dependency remains unresolved in the APAC corridor"


def _convert(tmp_path):
    return convert_document(FIXTURES / "deck.pptx", output_dir=tmp_path, use_cache=False)


def test_every_chunk_knows_which_slide_it_came_from(tmp_path):
    result = _convert(tmp_path)
    assert result.chunks, "the deck produced no chunks"
    assert all(chunk.pages for chunk in result.chunks), (
        "chunks without slide attribution: "
        f"{[c.chunk_id for c in result.chunks if not c.pages][:5]}"
    )


def test_slide_numbers_do_not_go_backwards(tmp_path):
    result = _convert(tmp_path)
    firsts = [chunk.pages[0] for chunk in result.chunks]
    assert firsts == sorted(firsts), firsts


def test_a_phrase_on_slide_14_is_cited_as_slide_14(tmp_path):
    result = _convert(tmp_path)
    hits = [chunk for chunk in result.chunks if NEEDLE in chunk.text]
    assert len(hits) == 1, f"expected one chunk to contain the needle, got {len(hits)}"
    assert hits[0].pages == [14], hits[0].pages


def test_chunks_carry_the_slide_title(tmp_path):
    result = _convert(tmp_path)
    hits = [chunk for chunk in result.chunks if NEEDLE in chunk.text]
    assert hits[0].section_path, "no section path"
    assert "Section 14" in hits[0].section_path


def test_markers_do_not_leak_into_chunk_text(tmp_path):
    result = _convert(tmp_path)
    for chunk in result.chunks:
        assert "Slide number" not in chunk.text
        assert "<!-- page:" not in chunk.text


def test_page_count_is_the_slide_count(tmp_path):
    assert _convert(tmp_path).document.page_count == 60
```

- [ ] **Step 3: Run tests to verify they fail before Task 1 is present**

Run: `uv run pytest tests/unit/test_slide_attribution.py -v`
Expected: PASS once Tasks 1–2 are done. If Tasks 1–2 are already committed,
verify the tests have teeth by temporarily making `normalize_slide_markers`
return `(markdown, None)` and confirming these tests fail; then restore it.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: PASS, clean

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/make_deck.py tests/fixtures/deck.pptx tests/unit/test_slide_attribution.py
git commit -m "test: prove a deck chunk can be cited as a slide number"
```

---

### Task 4: Say what a deck can and cannot give you

**Files:**
- Modify: `README.md` (the search/limitations prose near the lexical-search caveat)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: nothing. Documentation only.

- [ ] **Step 1: Document slide citation and the arrow limitation**

Add near the existing search caveat:

> **PowerPoint answers cite slide numbers.** A deck's chunks carry the slide
> they came from, the same way a PDF's carry the page — the field is called
> `pages` for both, and for a presentation it means slides. Speaker notes are
> extracted too, and are searchable.
>
> **What a deck does not give you: diagrams.** A slide with three boxes and two
> arrows extracts as three labels. The words survive, the relationships do not,
> so DocSift cannot answer what an arrow between two boxes meant. Images inside
> slides are not read at all — text in a screenshot is invisible to search.

- [ ] **Step 2: Add the changelog entry**

```markdown
## Unreleased

- **PowerPoint chunks now carry their slide number and title.** MarkItDown marks
  slide boundaries its own way, which nothing downstream recognised, so a deck's
  chunks came back with no attribution at all — no slide number, no title, and
  the raw markers sitting in the chunk text. Answers from a deck can now be
  cited by slide, the way a PDF is cited by page.
```

- [ ] **Step 3: Verify the claims**

Run: `uv run pytest tests/unit/test_slide_attribution.py -q`
Expected: PASS — every sentence added above is covered by a test.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: slide citations, and what a deck cannot tell you"
```

---

## Verification before merge

- [ ] `uv run pytest -q` — all pass
- [ ] `uv run ruff check . && uv run ruff format --check .` — clean
- [ ] Manual: convert a real deck and confirm the JSON shows sensible `pages`
      and `section_path` per chunk, not just that tests pass
- [ ] `docsift convert deck.pptx --no-cache` output contains no `Slide number`
- [ ] A PDF conversion is unchanged — diff `pages`/`section_path` against a
      pre-change run of `tests/fixtures/multipage.pdf`

## Deferred to a future version

Recorded so they are decisions rather than omissions:

- **OCR of images inside slides.** MarkItDown does not read them, so text in a
  screenshot or a picture of a table is invisible to search. Routing PPTX
  through Docling would fix it and would pull the entire PyTorch stack into a
  format that needs none of it today. Wants its own spec.
- **Diagram semantics.** Arrows, connectors and SmartArt relationships.
- **Visual descriptions via a vision model**, and progressive retrieval that
  sends a rendered slide image only when a question needs it.
- **Document generation** (Markdown → PPTX/DOCX/PDF).
