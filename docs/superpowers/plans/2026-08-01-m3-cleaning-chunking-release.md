# DocSift M3: Cleaning, Chunking, Caching, and v0.1 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the v0.1 pipeline — engine markdown is cleaned (headers/footers/page numbers stripped), chunked into token-budgeted heading-aware pieces (Docling's HybridChunker for PDFs, our markdown chunker otherwise), counted with real tiktoken, and cached — then prepare the 0.1.0 PyPI release.

**Architecture:** Pure processing modules (`cleaner.py`, `chunker.py`) operate on markdown strings. The `ConversionEngine.convert` signature gains an optional `options` parameter so the Docling adapter can chunk from its structured document (HybridChunker, mapped to neutral `Chunk` models inside `engines/` — no docling types escape). `conversion_service` orchestrates raw → clean → chunk → metrics, and a filesystem cache keyed on source hash + engine version + DocSift version + options short-circuits repeat conversions. Release prep adds version 0.1.0, CHANGELOG, and a trusted-publishing release workflow; the actual PyPI publish is user-gated.

**Tech Stack:** Adds `tiktoken` as a core dependency (small, wheels everywhere). HybridChunker comes from `docling-core`, already installed with the docling extra. No other new dependencies.

## Global Constraints

- Everything from prior plans still binds: uv only; lazy engine imports (`docsift --help` with no engines); no engine-specific types outside `engines/`; PDFs→Docling in auto mode; never log/print document contents (error text: type names only for non-DocSiftError); conventional commits; integration tests marked and excluded by default; CI parity — after any change to validation or engine resolution, re-run the unit suite with docling forced unavailable.
- Chunk defaults: `max_tokens=1000`, `overlap_tokens=100` (PRD: 600–900 target, 1,000 max, 80–120 overlap).
- Tokenizer: tiktoken `o200k_base` with a chars/4 fallback when tiktoken is unavailable; `estimate_tokens(text: str) -> int` signature is frozen.
- Cleaning must never alter heading text, list items, or table rows.
- Page markers are HTML comments `<!-- page: N -->` (PRD decision).
- Do NOT modify this plan file from an implementer subagent. Controller owns it. Do not push; controller pushes.
- Repo root: `/Users/anish/DocBridge/docsift`. HEAD at plan time: `5b2d8be`.

---

### Task 1: Real token estimation with tiktoken

**Files:**
- Modify: `pyproject.toml` (core dependencies), `src/docsift/processing/token_estimator.py`
- Test: `tests/unit/test_token_estimator.py`

**Interfaces:**
- Produces: `estimate_tokens(text: str) -> int` (unchanged signature) now using tiktoken `o200k_base` via a cached encoder, falling back to `_estimate_fallback(text)` (chars/4, the current heuristic, exposed for tests) when tiktoken is not importable. Existing callers (chunker-to-be, service, comparison) need no changes.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml` `[project] dependencies`, add `"tiktoken>=0.8",` after pydantic. Run `uv sync --all-extras` and confirm `uv run python -c "import tiktoken; print(tiktoken.get_encoding('o200k_base').name)"` prints `o200k_base`.

- [ ] **Step 2: Write the failing tests**

Replace the heuristic-specific test in `tests/unit/test_token_estimator.py` with:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_token_estimator.py -v`
Expected: `test_matches_tiktoken_o200k_exactly` FAILS (heuristic ≠ exact count); `_estimate_fallback` import fails.

- [ ] **Step 4: Implement**

Replace `src/docsift/processing/token_estimator.py`:

```python
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
```

- [ ] **Step 5: Run the full gate**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: all pass (token-count assertions elsewhere use `>= 1` style, unaffected), ruff clean.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/docsift/processing/token_estimator.py tests/unit/test_token_estimator.py
git commit -m "feat: exact token counts via tiktoken o200k_base with heuristic fallback"
```

---

### Task 2: Options models, schema additions, and engine signature

**Files:**
- Create: `src/docsift/core/options.py`
- Modify: `src/docsift/core/models.py`, `src/docsift/engines/base.py`, `src/docsift/engines/docling_engine.py`, `src/docsift/engines/markitdown_engine.py`
- Modify (mechanical fake updates): `tests/unit/test_registry.py`, `tests/unit/test_conversion_service.py`, `tests/unit/test_cli.py`, `tests/unit/test_comparison_service.py`
- Test: `tests/unit/test_options.py`

**Interfaces:**
- Produces (exact — every later task depends on these):

`src/docsift/core/options.py`:

```python
from pydantic import BaseModel, Field


class CleanOptions(BaseModel):
    remove_image_refs: bool = True
    keep_page_markers: bool = True
    remove_furniture: bool = True
    furniture_min_repeats: int = 3


class ChunkOptions(BaseModel):
    max_tokens: int = 1000
    overlap_tokens: int = 100


class ConversionOptions(BaseModel):
    clean: CleanOptions = Field(default_factory=CleanOptions)
    chunk: ChunkOptions = Field(default_factory=ChunkOptions)
```

- `core/models.py` additions: `ConversionMetrics` gains `raw_estimated_tokens: int | None = None` and `duplicate_lines_removed: int = 0`; `EngineOutput` gains `chunks: list[Chunk] | None = None` (None = "engine did not chunk; service falls back").
- `engines/base.py`: `convert` becomes `def convert(self, path: Path, options: ConversionOptions | None = None) -> EngineOutput` (abstract); new NON-abstract classmethod `def version(cls) -> str: return "unknown"` (adapters override with their real package version — needed by Task 7's cache key without running a conversion).
- Both adapters: accept `options` (markitdown ignores it for now; docling uses it in Task 5), and override `version()` returning `metadata.version("markitdown")` / `metadata.version("docling")` guarded by `is_available()` (return "unknown" when not installed).
- Every test fake's `convert` gains `options=None` — mechanical: `FakeEngine`/`UnavailableEngine` (test_registry), `StubEngine`/`ExplodingEngine`/`StructuredFailureEngine`/`EmptyEngine` (test_conversion_service), the stub classes in test_cli, `GoodEngine`/`BadEngine`/`SecretEngine` (test_comparison_service).

- [ ] **Step 1: Write the failing test**

`tests/unit/test_options.py`:

```python
from docsift.core.options import ChunkOptions, CleanOptions, ConversionOptions


def test_defaults_match_prd():
    options = ConversionOptions()
    assert options.chunk.max_tokens == 1000
    assert options.chunk.overlap_tokens == 100
    assert options.clean.remove_image_refs is True
    assert options.clean.keep_page_markers is True


def test_options_serialize_deterministically():
    a = ConversionOptions().model_dump_json()
    b = ConversionOptions(
        clean=CleanOptions(), chunk=ChunkOptions(max_tokens=1000, overlap_tokens=100)
    ).model_dump_json()
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_options.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement all interface changes**

Create `core/options.py` exactly as in the Interfaces block. Apply the `models.py` field additions. Update `engines/base.py`:

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from docsift.core.models import EngineOutput
from docsift.core.options import ConversionOptions


class ConversionEngine(ABC):
    """One document-conversion backend. Implementations keep their imports lazy."""

    name: ClassVar[str]

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """True when the engine's optional dependency is importable."""

    @classmethod
    def version(cls) -> str:
        """Installed engine package version; 'unknown' when unavailable."""
        return "unknown"

    @abstractmethod
    def convert(self, path: Path, options: ConversionOptions | None = None) -> EngineOutput:
        """Convert the file at `path`. Raises on failure; never returns None."""
```

Adapters: add `options: ConversionOptions | None = None` to `convert` (unused for now: name it `options` and leave a no-op — docling wires it in Task 5) and add:

```python
@classmethod
def version(cls) -> str:
    if not cls.is_available():
        return "unknown"
    return metadata.version("markitdown")  # / "docling" in docling_engine.py
```

Then update every listed test fake's `convert` signature to `def convert(self, path: Path, options=None) -> EngineOutput:` — no other fake changes.

- [ ] **Step 4: Run the full gate**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: all pass (service still calls `convert(path)` — the optional parameter keeps it compatible until Task 6), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/core src/docsift/engines tests/unit
git commit -m "feat: add conversion options, schema fields, and engine version/options surface"
```

---

### Task 3: Markdown cleaner

**Files:**
- Create: `src/docsift/processing/cleaner.py`
- Test: `tests/unit/test_cleaner.py`

**Interfaces:**
- Consumes: `CleanOptions`.
- Produces:

```python
class CleanStats(BaseModel):
    duplicate_lines_removed: int = 0
    page_number_lines_removed: int = 0
    furniture_lines_removed: int = 0
    image_refs_removed: int = 0


def clean_markdown(
    markdown: str, options: CleanOptions | None = None
) -> tuple[str, CleanStats]: ...
```

Behavior (in order): strip trailing whitespace per line → replace the k-th `<!-- page-break -->` with `<!-- page: k+1 -->` when `keep_page_markers` (drop entirely otherwise) → remove image-reference-only lines when `remove_image_refs` → remove page-number-only lines (`12`, `Page 12`, `12 of 340`, case-insensitive) → remove "furniture" (when `remove_furniture`: exact non-empty lines of 4–79 chars, not headings/table rows/list items/page markers, occurring ≥ `furniture_min_repeats` times — all occurrences removed) → collapse consecutive identical non-empty lines to one → collapse 2+ blank lines to one blank line → single trailing newline. Heading text, list items, and table rows are never modified or removed. **Fenced code blocks (``` or ~~~) are fully exempt from every stage** — a duplicated statement in a code sample or a repeated log line is legitimate content, not furniture.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_cleaner.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cleaner.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`src/docsift/processing/cleaner.py`:

```python
import re
from collections import Counter

from pydantic import BaseModel

from docsift.core.options import CleanOptions

PAGE_BREAK = "<!-- page-break -->"
_PAGE_MARKER = re.compile(r"^<!-- page: \d+ -->$")
_PAGE_NUMBER = re.compile(r"^(page\s+)?\d+(\s+of\s+\d+)?$", re.IGNORECASE)
_IMAGE_REF = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")
_LIST_ITEM = re.compile(r"^[-*+] |^\d+[.)] ")


class CleanStats(BaseModel):
    duplicate_lines_removed: int = 0
    page_number_lines_removed: int = 0
    furniture_lines_removed: int = 0
    image_refs_removed: int = 0


def _is_protected(stripped: str) -> bool:
    """Lines cleaning must never remove: headings, table rows, list items, page markers."""
    return (
        stripped.startswith("#")
        or stripped.startswith("|")
        or bool(_LIST_ITEM.match(stripped))
        or bool(_PAGE_MARKER.match(stripped))
    )


def clean_markdown(markdown: str, options: CleanOptions | None = None) -> tuple[str, CleanStats]:
    options = options or CleanOptions()
    stats = CleanStats()
    lines = [line.rstrip() for line in markdown.splitlines()]

    page = 1
    numbered: list[str] = []
    for line in lines:
        if line.strip() == PAGE_BREAK:
            page += 1
            if options.keep_page_markers:
                numbered.append(f"<!-- page: {page} -->")
            continue
        numbered.append(line)
    lines = numbered

    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if options.remove_image_refs and _IMAGE_REF.match(stripped):
            stats.image_refs_removed += 1
            continue
        if stripped and not _is_protected(stripped) and _PAGE_NUMBER.match(stripped):
            stats.page_number_lines_removed += 1
            continue
        kept.append(line)
    lines = kept

    if options.remove_furniture:
        candidates = Counter(
            line.strip()
            for line in lines
            if 4 <= len(line.strip()) < 80 and not _is_protected(line.strip())
        )
        furniture = {
            text for text, count in candidates.items() if count >= options.furniture_min_repeats
        }
        kept = []
        for line in lines:
            if line.strip() in furniture:
                stats.furniture_lines_removed += 1
                continue
            kept.append(line)
        lines = kept

    deduped: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and deduped and deduped[-1].strip() == stripped and not _is_protected(stripped):
            stats.duplicate_lines_removed += 1
            continue
        deduped.append(line)
    lines = deduped

    collapsed: list[str] = []
    for line in lines:
        if not line.strip() and collapsed and not collapsed[-1].strip():
            continue
        collapsed.append(line)
    while collapsed and not collapsed[0].strip():
        collapsed.pop(0)
    while collapsed and not collapsed[-1].strip():
        collapsed.pop()
    return "\n".join(collapsed) + "\n", stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cleaner.py -v && uv run ruff check .`
Expected: 8 passed, ruff clean. If an individual assertion count is off by one, debug the pipeline order — do not change the test's expected counts; they encode the spec.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/processing/cleaner.py tests/unit/test_cleaner.py
git commit -m "feat: add markdown cleaner (furniture, page numbers, dedup, page markers)"
```

---

### Task 4: Fallback markdown chunker

**Files:**
- Create: `src/docsift/processing/chunker.py`
- Test: `tests/unit/test_chunker.py`

**Interfaces:**
- Consumes: `Chunk`, `ChunkOptions`, `estimate_tokens`.
- Produces: `chunk_markdown(markdown: str, document_id: str, options: ChunkOptions | None = None) -> list[Chunk]`. Heading-aware (section_path from the heading stack), token-budgeted (chunks stay ≤ `max_tokens` except a single indivisible block may exceed it), overlap (each chunk after the first begins with the previous chunk's trailing lines up to `overlap_tokens`), tables kept intact (oversized tables split by rows, header + separator repeated per part), a heading is never the last block of a chunk (exit criterion: headings stay with their first paragraph), pages from `<!-- page: N -->` markers, stable IDs `f"{document_id}_c{index:03d}"`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_chunker.py` (property-style — asserts the exit criteria, not exact boundaries):

```python
from docsift.core.options import ChunkOptions
from docsift.processing.chunker import chunk_markdown

PARA = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod. "
DOC = (
    "# Report\n\n"
    "<!-- page: 1 -->\n\n"
    "## Revenue\n\n" + (PARA * 12) + "\n\n" + (PARA * 12) + "\n\n"
    "<!-- page: 2 -->\n\n"
    "## Expenses\n\n" + (PARA * 12) + "\n\n"
    "| Quarter | Value |\n|---|---|\n| Q1 | 100 |\n| Q2 | 120 |\n\n"
    "## Risks\n\n" + (PARA * 3) + "\n"
)
SMALL = ChunkOptions(max_tokens=250, overlap_tokens=40)


def test_chunks_respect_token_budget():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert chunk.estimated_tokens <= SMALL.max_tokens + SMALL.overlap_tokens


def test_no_chunk_ends_with_a_heading():
    for chunk in chunk_markdown(DOC, "doc_abc", SMALL):
        last_line = chunk.text.strip().splitlines()[-1]
        assert not last_line.startswith("#")


def test_stable_ids_and_prefix():
    first = [c.chunk_id for c in chunk_markdown(DOC, "doc_abc", SMALL)]
    second = [c.chunk_id for c in chunk_markdown(DOC, "doc_abc", SMALL)]
    assert first == second
    assert first[0] == "doc_abc_c000"


def test_section_paths_follow_headings():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    assert any(chunk.section_path == ["Report", "Revenue"] for chunk in chunks)
    assert any(chunk.section_path == ["Report", "Expenses"] for chunk in chunks)


def test_pages_tracked_from_markers():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    assert any(2 in chunk.pages for chunk in chunks)
    assert all("<!-- page:" not in chunk.text for chunk in chunks)


def test_small_table_stays_intact():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    holders = [c for c in chunks if "| Q1 | 100 |" in c.text]
    assert len(holders) == 1
    assert "| Quarter | Value |" in holders[0].text


def test_oversized_table_splits_with_repeated_header():
    rows = "\n".join(f"| row-{i} | {'x' * 60} |" for i in range(80))
    table_doc = f"# T\n\n| K | V |\n|---|---|\n{rows}\n"
    chunks = chunk_markdown(table_doc, "doc_t", ChunkOptions(max_tokens=300, overlap_tokens=0))
    table_chunks = [c for c in chunks if "| row-" in c.text]
    assert len(table_chunks) >= 2
    for chunk in table_chunks:
        assert "| K | V |" in chunk.text


def test_overlap_carries_previous_tail():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    assert len(chunks) >= 2
    prev_tail = chunks[0].text.strip().splitlines()[-1]
    assert prev_tail in chunks[1].text


def test_empty_markdown_yields_no_chunks():
    assert chunk_markdown("", "doc_e") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_chunker.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`src/docsift/processing/chunker.py`:

```python
import re

from docsift.core.models import Chunk
from docsift.core.options import ChunkOptions
from docsift.processing.token_estimator import estimate_tokens

_PAGE_MARKER = re.compile(r"^<!-- page: (\d+) -->$")
_HEADING = re.compile(r"^(#{1,6}) (.*)$")


def _block_text(block: dict) -> str:
    return "\n".join(block["lines"])


def _tokens(block: dict) -> int:
    return estimate_tokens(_block_text(block))


def _parse_blocks(markdown: str) -> list[dict]:
    """Split into heading/table/text blocks; track page from markers; drop markers."""
    blocks: list[dict] = []
    page: int | None = None
    heading_stack: list[tuple[int, str]] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        marker = _PAGE_MARKER.match(stripped)
        if marker:
            page = int(marker.group(1))
            i += 1
            continue
        if not stripped:
            i += 1
            continue
        heading = _HEADING.match(lines[i])
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            heading_stack = [h for h in heading_stack if h[0] < level]
            heading_stack.append((level, title))
            blocks.append(
                {
                    "kind": "heading",
                    "lines": [lines[i]],
                    "page": page,
                    "path": [t for _, t in heading_stack],
                }
            )
            i += 1
            continue
        if stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            blocks.append(
                {
                    "kind": "table",
                    "lines": rows,
                    "page": page,
                    "path": [t for _, t in heading_stack],
                }
            )
            continue
        para = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not _HEADING.match(lines[i])
            and not lines[i].strip().startswith("|")
            and not _PAGE_MARKER.match(lines[i].strip())
        ):
            para.append(lines[i])
            i += 1
        blocks.append(
            {"kind": "text", "lines": para, "page": page, "path": [t for _, t in heading_stack]}
        )
    return blocks


def _split_table(rows: list[str], max_tokens: int) -> list[list[str]]:
    header, body = rows[:2], rows[2:]
    if not body:
        return [rows]
    parts: list[list[str]] = []
    current = list(header)
    for row in body:
        if len(current) > len(header) and estimate_tokens("\n".join(current + [row])) > max_tokens:
            parts.append(current)
            current = list(header)
        current.append(row)
    parts.append(current)
    return parts


def _tail_lines(text: str, overlap_tokens: int) -> list[str]:
    tail: list[str] = []
    for line in reversed(text.splitlines()):
        tail.insert(0, line)
        if estimate_tokens("\n".join(tail)) >= overlap_tokens:
            break
    return tail


def chunk_markdown(
    markdown: str, document_id: str, options: ChunkOptions | None = None
) -> list[Chunk]:
    options = options or ChunkOptions()
    blocks: list[dict] = []
    for block in _parse_blocks(markdown):
        if block["kind"] == "table" and _tokens(block) > options.max_tokens:
            for part in _split_table(block["lines"], options.max_tokens):
                blocks.append({**block, "lines": part})
        else:
            blocks.append(block)
    if not blocks:
        return []

    chunks: list[Chunk] = []
    current: list[dict] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        carried = None
        if len(current) > 1 and current[-1]["kind"] == "heading":
            carried = current.pop()
        content = [b for b in current if b["kind"] != "overlap"]
        if not content:
            current = [carried] if carried else []
            return
        text = "\n\n".join(_block_text(b) for b in current)
        pages = sorted({b["page"] for b in content if b["page"] is not None})
        chunks.append(
            Chunk(
                chunk_id=f"{document_id}_c{len(chunks):03d}",
                text=text,
                estimated_tokens=estimate_tokens(text),
                section_path=list(content[0]["path"]),
                pages=pages,
            )
        )
        overlap: list[dict] = []
        if options.overlap_tokens > 0:
            overlap = [
                {
                    "kind": "overlap",
                    "lines": _tail_lines(text, options.overlap_tokens),
                    "page": pages[-1] if pages else None,
                    "path": list(content[-1]["path"]),
                }
            ]
        current = overlap + ([carried] if carried else [])

    running = 0
    for block in blocks:
        block_tokens = _tokens(block)
        has_content = any(b["kind"] not in ("overlap",) for b in current)
        if has_content and running + block_tokens > options.max_tokens:
            flush()
            running = sum(_tokens(b) for b in current)
        current.append(block)
        running += block_tokens
    flush()
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_chunker.py -v && uv run ruff check . && uv run ruff format .`
Expected: 9 passed. If a property test fails, fix the chunker logic — the properties are the spec (they encode the M3 exit criteria). Do not loosen assertions.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/processing/chunker.py tests/unit/test_chunker.py
git commit -m "feat: add heading-aware token-budgeted markdown chunker with overlap"
```

---

### Task 5: Docling HybridChunker integration and page markers

**Files:**
- Modify: `src/docsift/engines/docling_engine.py`
- Test: `tests/integration/test_docling_engine.py` (append), `tests/unit/test_docling_engine_unit.py` (append)

**Interfaces:**
- Consumes: `ChunkOptions` (via `options.chunk`), `Chunk`, `ConversionWarning`, `estimate_tokens`.
- Produces: `DoclingEngine.convert(path, options)` now (a) exports markdown with `page_break_placeholder="<!-- page-break -->"` when the installed docling supports that keyword (fall back silently via `except TypeError`), and (b) fills `EngineOutput.chunks` using docling-core's `HybridChunker` with a tiktoken `o200k_base` tokenizer capped at `options.chunk.max_tokens` — chunk IDs are engine-local (`"c000"`, `"c001"`, …; the service prefixes the document id in Task 6), `section_path` from chunk meta headings, `pages` from doc-item provenance. Any failure in the chunking path yields `chunks=None` plus a `ConversionWarning(code="docling_chunker_unavailable", ...)` naming only the exception type — conversion itself must still succeed (service falls back to the markdown chunker).

**API drift clause:** the docling-core surface expected here is `docling_core.transforms.chunker.hybrid_chunker.HybridChunker` (constructor kwarg `tokenizer=`, methods `chunk(dl_doc=...)` and `contextualize(chunk=...)`) and `docling_core.transforms.chunker.tokenizer.openai.OpenAITokenizer` (kwargs `tokenizer=` [a tiktoken encoding], `max_tokens=`). Verify against the installed docling-core before writing code (`uv run python -c "from docling_core.transforms.chunker.hybrid_chunker import HybridChunker; import inspect; print(inspect.signature(HybridChunker))"` etc.). If the real surface differs, adapt the import paths/kwargs to the installed version and record exactly what differed in your report; if it differs so much the mapping below can't be expressed, STOP and report BLOCKED with the actual surface.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_docling_engine.py`:

```python
def test_convert_produces_hybrid_chunks(tmp_path):
    from docsift.core.options import ChunkOptions, ConversionOptions

    options = ConversionOptions(chunk=ChunkOptions(max_tokens=200, overlap_tokens=0))
    output = DoclingEngine().convert(FIXTURES / "multipage.pdf", options)
    assert output.chunks, "docling should produce HybridChunker chunks"
    for chunk in output.chunks:
        assert chunk.text.strip()
        assert chunk.estimated_tokens <= 200
        assert chunk.chunk_id.startswith("c")
    assert any(chunk.pages for chunk in output.chunks)


def test_markdown_contains_page_breaks_when_supported():
    output = DoclingEngine().convert(FIXTURES / "multipage.pdf")
    assert output.page_count == 3
```

Append to `tests/unit/test_docling_engine_unit.py` (runs in CI without docling):

```python
def test_chunking_failure_degrades_to_warning(monkeypatch, tmp_path):
    import sys
    import types

    class FakeDocument:
        def export_to_markdown(self, **kwargs):
            return "# Hi\n\nBody."

        pages = {1: object()}
        texts = []

    class FakeResult:
        document = FakeDocument()

    class FakeConverter:
        def convert(self, path):
            return FakeResult()

    fake_module = types.ModuleType("docling.document_converter")
    fake_module.DocumentConverter = FakeConverter
    fake_package = types.ModuleType("docling")
    monkeypatch.setitem(sys.modules, "docling", fake_package)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_module)
    monkeypatch.setitem(sys.modules, "docling_core", None)  # forces chunker ImportError

    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    output = DoclingEngine().convert(pdf)
    assert output.markdown.startswith("# Hi")
    assert output.chunks is None
    assert any(w.code == "docling_chunker_unavailable" for w in output.warnings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_docling_engine_unit.py -v` and `uv run pytest tests/integration -m integration -v`
Expected: new tests FAIL (`chunks` always None today; warning absent).

- [ ] **Step 3: Implement**

Rework `DoclingEngine.convert` in `src/docsift/engines/docling_engine.py`:

```python
def convert(self, path: Path, options: ConversionOptions | None = None) -> EngineOutput:
    from docling.document_converter import DocumentConverter

    chunk_options = options.chunk if options else ChunkOptions()
    try:
        result = DocumentConverter().convert(str(path))
        document = result.document
        try:
            markdown = document.export_to_markdown(page_break_placeholder="<!-- page-break -->")
        except TypeError:  # older docling without the keyword
            markdown = document.export_to_markdown()
    except Exception as exc:
        # Exception text can quote document content; expose only the type name.
        raise ConversionFailedError(
            f"docling failed on '{path.name}': {type(exc).__name__}"
        ) from exc
    chunks, warnings = self._chunk(document, chunk_options)
    title = None
    for item in getattr(document, "texts", []):
        if type(item).__name__ == "TitleItem":
            title = getattr(item, "text", None)
            break
    page_count = len(document.pages) if getattr(document, "pages", None) else None
    return EngineOutput(
        markdown=markdown,
        title=title,
        page_count=page_count,
        chunks=chunks,
        warnings=warnings,
        engine_version=metadata.version("docling"),
    )


def _chunk(self, document, chunk_options):
    """Map docling HybridChunker output to neutral Chunk models; degrade gracefully."""
    from docsift.processing.token_estimator import estimate_tokens

    try:
        import tiktoken
        from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
        from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer

        tokenizer = OpenAITokenizer(
            tokenizer=tiktoken.get_encoding("o200k_base"),
            max_tokens=chunk_options.max_tokens,
        )
        chunker = HybridChunker(tokenizer=tokenizer)
        chunks: list[Chunk] = []
        for index, docling_chunk in enumerate(chunker.chunk(dl_doc=document)):
            text = chunker.contextualize(chunk=docling_chunk)
            headings = list(getattr(docling_chunk.meta, "headings", None) or [])
            pages = sorted(
                {
                    prov.page_no
                    for item in getattr(docling_chunk.meta, "doc_items", []) or []
                    for prov in getattr(item, "prov", []) or []
                }
            )
            chunks.append(
                Chunk(
                    chunk_id=f"c{index:03d}",
                    text=text,
                    estimated_tokens=estimate_tokens(text),
                    section_path=headings,
                    pages=pages,
                )
            )
        return chunks, []
    except Exception as exc:
        return None, [
            ConversionWarning(
                code="docling_chunker_unavailable",
                message=(
                    "HybridChunker unavailable "
                    f"({type(exc).__name__}); markdown chunker will be used"
                ),
            )
        ]
```

Add the needed imports at module top (`ChunkOptions`, `ConversionOptions` from `docsift.core.options`; `Chunk`, `ConversionWarning` join the existing model imports — all docsift-internal, so top-level is fine; `docling*`/`tiktoken` stay lazy).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_docling_engine_unit.py -v && uv run pytest tests/integration -m integration -v && uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: all green (integration lane uses cached models; the new chunk test may download the tokenizer vocabulary once).

- [ ] **Step 5: Commit**

```bash
git add src/docsift/engines/docling_engine.py tests/integration/test_docling_engine.py tests/unit/test_docling_engine_unit.py
git commit -m "feat: docling adapter emits HybridChunker chunks and page-break markers"
```

---

### Task 6: Service pipeline (clean → chunk → metrics) and CLI flags

**Files:**
- Modify: `src/docsift/services/conversion_service.py`, `src/docsift/cli/main.py`
- Test: `tests/unit/test_conversion_service.py` (append), `tests/unit/test_cli.py` (append)

**Interfaces:**
- Consumes: `clean_markdown`, `chunk_markdown`, `ConversionOptions`, updated `EngineOutput.chunks`.
- Produces: `convert_document(path, engine="auto", output_dir=None, options: ConversionOptions | None = None) -> ConversionResult` where: engine gets called as `engine_impl.convert(path, options)`; raw markdown token count recorded as `metrics.raw_estimated_tokens`; cleaned markdown becomes `document.markdown` and drives `characters`/`words`/`estimated_tokens`; `metrics.duplicate_lines_removed = stats.duplicate_lines_removed + stats.furniture_lines_removed`; chunks = engine chunks with IDs re-prefixed `f"{document_id}_{chunk.chunk_id}"` when `output.chunks is not None`, else `chunk_markdown(cleaned, document_id, options.chunk)`; engine warnings carried through (plus the existing `empty_output` warning against the cleaned markdown).
- CLI `convert` gains `--max-tokens INT` (default 1000), `--overlap INT` (default 100), `--keep-image-refs` flag (default off = images removed) and prints `chunks: N` after the token line. Validation ordering (`_validate` before engine resolution) MUST stay untouched — CI-parity rule.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_conversion_service.py`:

```python
NOISY_MD = (
    "# Title\n\nReal paragraph one.\n\nCorp Confidential\n<!-- page-break -->\n"
    "Corp Confidential\n\nSecond paragraph.\n<!-- page-break -->\nCorp Confidential\n\n42\n"
)


class NoisyEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        return EngineOutput(markdown=NOISY_MD, engine_version="9.9.9")


class PrechunkedEngine(NoisyEngine):
    def convert(self, path: Path, options=None) -> EngineOutput:
        from docsift.core.models import Chunk

        return EngineOutput(
            markdown="# T\n\nBody.",
            engine_version="9.9.9",
            chunks=[Chunk(chunk_id="c000", text="Body.", estimated_tokens=2)],
        )


def test_pipeline_cleans_and_chunks(stub_engine, text_file):
    register_engine("markitdown", NoisyEngine)
    try:
        result = convert_document(text_file)
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", StubEngine)
    assert "Corp Confidential" not in result.document.markdown
    assert "<!-- page: 2 -->" in result.document.markdown
    assert result.metrics.raw_estimated_tokens is not None
    assert result.metrics.raw_estimated_tokens > result.metrics.estimated_tokens
    assert result.metrics.duplicate_lines_removed >= 3
    assert result.chunks
    assert result.chunks[0].chunk_id == f"{result.document_id}_c000"


def test_engine_chunks_win_over_fallback(stub_engine, text_file):
    register_engine("markitdown", PrechunkedEngine)
    try:
        result = convert_document(text_file)
    finally:
        unregister_engine("markitdown")
        register_engine("markitdown", StubEngine)
    assert len(result.chunks) == 1
    assert result.chunks[0].chunk_id == f"{result.document_id}_c000"
    assert result.chunks[0].text == "Body."
```

(The `stub_engine` fixture already registers/unregisters `StubEngine` around each test; the inner re-register/restore pattern matches the file's existing style.)

Append to `tests/unit/test_cli.py`:

```python
def test_convert_reports_chunks_and_accepts_chunk_flags(stub_engine, tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        ["convert", str(source), "--output", str(out), "--max-tokens", "500", "--overlap", "50"],
    )
    assert result.exit_code == 0, result.output
    assert "chunks:" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_conversion_service.py tests/unit/test_cli.py -v`
Expected: new tests FAIL (no cleaning/chunking yet; no flags).

- [ ] **Step 3: Implement**

In `conversion_service.py`, inside `convert_document` (keeping `_validate` → router → registry → `build_source_metadata` order):

```python
def convert_document(
    path: Path,
    engine: str = "auto",
    output_dir: Path | None = None,
    options: ConversionOptions | None = None,
) -> ConversionResult:
    options = options or ConversionOptions()
    ...
    output = engine_impl.convert(path, options)  # was convert(path)
    ...
    raw_markdown = output.markdown
    markdown, clean_stats = clean_markdown(raw_markdown, options.clean)
    document_id = f"doc_{source.sha256[:12]}"
    if output.chunks is not None:
        chunks = [
            chunk.model_copy(update={"chunk_id": f"{document_id}_{chunk.chunk_id}"})
            for chunk in output.chunks
        ]
    else:
        chunks = chunk_markdown(markdown, document_id, options.chunk)
    ...
    metrics = ConversionMetrics(
        characters=len(markdown),
        words=len(markdown.split()),
        estimated_tokens=estimate_tokens(markdown),
        raw_estimated_tokens=estimate_tokens(raw_markdown),
        duplicate_lines_removed=(
            clean_stats.duplicate_lines_removed + clean_stats.furniture_lines_removed
        ),
    )
```

`document.markdown` becomes the cleaned markdown; `chunks=chunks` goes into the result; the `empty_output` warning checks the cleaned markdown; artifact writing unchanged (writes cleaned markdown). Add imports for `clean_markdown`, `chunk_markdown`, `ConversionOptions`.

In `cli/main.py` `convert`:

```python
max_tokens: int = (typer.Option(1000, help="Maximum tokens per chunk."),)
overlap: int = (typer.Option(100, help="Token overlap between chunks."),)
keep_image_refs: bool = (
    typer.Option(False, "--keep-image-refs", help="Keep image references in the Markdown."),
)
```

build the options and pass them:

```python
    from docsift.core.options import ChunkOptions, CleanOptions, ConversionOptions

    options = ConversionOptions(
        clean=CleanOptions(remove_image_refs=not keep_image_refs),
        chunk=ChunkOptions(max_tokens=max_tokens, overlap_tokens=overlap),
    )
    result = convert_document(path, engine=engine, output_dir=output, options=options)
```

and print `typer.echo(f"chunks: {len(result.chunks)}")` after the token line.

- [ ] **Step 4: Run the full gate + CI parity check**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`
Then CI parity (docling forced unavailable):

```bash
uv run python -c "
import docsift.engines.docling_engine as d
d.DoclingEngine.is_available = classmethod(lambda cls: False)
import pytest, sys
sys.exit(pytest.main(['-q', 'tests/unit']))
"
```

Expected: everything green in both runs.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/services/conversion_service.py src/docsift/cli/main.py tests/unit/test_conversion_service.py tests/unit/test_cli.py
git commit -m "feat: wire clean-chunk-count pipeline into conversion service and CLI"
```

---

### Task 7: Filesystem result cache

**Files:**
- Create: `src/docsift/storage/__init__.py` (empty), `src/docsift/storage/cache.py`
- Modify: `src/docsift/services/conversion_service.py`, `src/docsift/services/comparison_service.py`, `src/docsift/cli/main.py`
- Test: `tests/unit/test_cache.py`, `tests/unit/test_cli.py` (append)

**Interfaces:**
- Produces `storage/cache.py`:

```python
def cache_dir() -> Path  # $DOCSIFT_CACHE_DIR or ~/.cache/docsift
def cache_key(source_sha256: str, engine_name: str, engine_version: str,
              docsift_version: str, options: ConversionOptions) -> str  # sha256 hex of the joined material
def load_cached(key: str) -> ConversionResult | None   # None on miss OR unparsable entry
def store_cached(key: str, result: ConversionResult) -> None  # writes {key}.json atomically (tmp + os.replace)
```

- `convert_document` gains `use_cache: bool = True`: on hit, returns the cached result with `conversion.cached = True` (artifacts still written when `output_dir` given); on miss, converts then stores. Cache lookup happens AFTER validation + engine resolution + `build_source_metadata` (the key needs the sha and `engine_impl.version()`).
- `compare_document` passes `use_cache=False` to every run — timing comparisons must measure real conversions.
- CLI `convert` gains `--no-cache` flag.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_cache.py`:

```python
from pathlib import Path

import pytest

from docsift.core.models import EngineOutput
from docsift.core.options import ChunkOptions, ConversionOptions
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine
from docsift.services.conversion_service import convert_document
from docsift.storage.cache import cache_key


class CountingEngine(ConversionEngine):
    name = "markitdown"
    calls = 0

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path, options=None) -> EngineOutput:
        type(self).calls += 1
        return EngineOutput(markdown="# Cached\n\nBody.", engine_version="9.9.9")


@pytest.fixture
def counting_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    CountingEngine.calls = 0
    register_engine("markitdown", CountingEngine)
    yield CountingEngine
    unregister_engine("markitdown")


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    file = tmp_path / "note.txt"
    file.write_text("hello world", encoding="utf-8")
    return file


def test_second_conversion_hits_cache(counting_engine, text_file):
    first = convert_document(text_file)
    second = convert_document(text_file)
    assert counting_engine.calls == 1
    assert first.conversion.cached is False
    assert second.conversion.cached is True
    assert second.document.markdown == first.document.markdown


def test_no_cache_bypasses(counting_engine, text_file):
    convert_document(text_file)
    convert_document(text_file, use_cache=False)
    assert counting_engine.calls == 2


def test_option_change_is_a_cache_miss(counting_engine, text_file):
    convert_document(text_file)
    convert_document(text_file, options=ConversionOptions(chunk=ChunkOptions(max_tokens=500)))
    assert counting_engine.calls == 2


def test_key_varies_with_every_component():
    base = dict(
        source_sha256="a" * 64,
        engine_name="docling",
        engine_version="2.0",
        docsift_version="0.1.0",
        options=ConversionOptions(),
    )
    key = cache_key(**base)
    assert key != cache_key(**{**base, "source_sha256": "b" * 64})
    assert key != cache_key(**{**base, "engine_version": "2.1"})
    assert key != cache_key(**{**base, "docsift_version": "0.2.0"})
    assert key != cache_key(
        **{**base, "options": ConversionOptions(chunk=ChunkOptions(max_tokens=99))}
    )
```

Append to `tests/unit/test_cli.py`:

```python
def test_convert_no_cache_flag_accepted(stub_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["convert", str(source), "--output", str(tmp_path / "o"), "--no-cache"]
    )
    assert result.exit_code == 0, result.output
```

Also add `monkeypatch.setenv("DOCSIFT_CACHE_DIR", ...)` to any existing CLI/service test that would otherwise write to the real user cache (`test_convert_writes_output`, `test_pipeline_cleans_and_chunks`, `test_engine_chunks_win_over_fallback`, and the comparison-service tests via one autouse fixture in each file if simpler — implementer's judgment, but NO test may touch `~/.cache/docsift`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_cache.py -v`
Expected: FAIL — `docsift.storage` missing.

- [ ] **Step 3: Implement**

`src/docsift/storage/cache.py`:

```python
import hashlib
import os
import tempfile
from pathlib import Path

from docsift.core.models import ConversionResult
from docsift.core.options import ConversionOptions


def cache_dir() -> Path:
    override = os.environ.get("DOCSIFT_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".cache" / "docsift"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_key(
    source_sha256: str,
    engine_name: str,
    engine_version: str,
    docsift_version: str,
    options: ConversionOptions,
) -> str:
    material = "\n".join(
        [source_sha256, engine_name, engine_version, docsift_version, options.model_dump_json()]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def load_cached(key: str) -> ConversionResult | None:
    entry = cache_dir() / f"{key}.json"
    if not entry.is_file():
        return None
    try:
        return ConversionResult.model_validate_json(entry.read_text(encoding="utf-8"))
    except ValueError:
        return None


def store_cached(key: str, result: ConversionResult) -> None:
    target = cache_dir() / f"{key}.json"
    handle = tempfile.NamedTemporaryFile(
        "w", dir=target.parent, suffix=".tmp", delete=False, encoding="utf-8"
    )
    try:
        handle.write(result.model_dump_json(indent=2))
        handle.close()
        os.replace(handle.name, target)
    except OSError:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise
```

Wire into `convert_document` (signature gains `use_cache: bool = True`): after `source = build_source_metadata(path)`:

```python
key = cache_key(source.sha256, engine_name, engine_impl.version(), __version__, options)
if use_cache:
    cached = load_cached(key)
    if cached is not None:
        cached = cached.model_copy(deep=True)
        cached.conversion.cached = True
        _write_artifacts(cached, path, output_dir)
        return cached
```

Extract the existing artifact-writing block into `_write_artifacts(result, path, output_dir)` (no-op when `output_dir is None`) and call it in both the cached and fresh paths; call `store_cached(key, result)` before returning a fresh result when `use_cache`. In `comparison_service._run_engine`, call `convert_document(..., use_cache=False)`. In the CLI, add `no_cache: bool = typer.Option(False, "--no-cache", help="Convert even if a cached result exists.")` and pass `use_cache=not no_cache`.

- [ ] **Step 4: Run the full gate + CI parity check**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .` and the docling-unavailable one-liner from Task 6 Step 4.
Expected: all green both ways; no test writes to `~/.cache/docsift` (verify: `ls ~/.cache/docsift 2>/dev/null | wc -l` unchanged before/after the suite, or the directory doesn't exist).

- [ ] **Step 5: Commit**

```bash
git add src/docsift/storage src/docsift/services src/docsift/cli/main.py tests/unit/test_cache.py tests/unit/test_cli.py
git commit -m "feat: cache conversion results keyed on source, engine, version, and options"
```

---

### Task 8: v0.1.0 release preparation and M3 exit verification

**Files:**
- Modify: `pyproject.toml` + `src/docsift/__init__.py` (version 0.1.0), `README.md`
- Create: `CHANGELOG.md`, `.github/workflows/release.yml`

**Interfaces:**
- Produces: version `0.1.0` everywhere; changelog; a release workflow that builds with uv and publishes to PyPI via **trusted publishing** when a GitHub release is published (no tokens in the repo); README documenting chunking/cleaning flags and cache behavior. The actual PyPI publish is NOT part of this task — it requires the user to configure the PyPI trusted publisher first (controller asks the user).

- [ ] **Step 1: Bump the version**

`pyproject.toml`: `version = "0.1.0"`. `src/docsift/__init__.py`: `__version__ = "0.1.0"`. Run `uv sync` (refreshes the lock's own-package version) and `uv run pytest tests/test_package.py -v` (the semver regex accepts it).

- [ ] **Step 2: Write CHANGELOG.md**

```markdown
# Changelog

## 0.1.0 — 2026-08-01

First release.

- Convert PDFs (Docling) and Office/HTML/CSV/EPUB files (MarkItDown) to clean
  Markdown plus a normalized JSON result — fully local, no cloud APIs.
- Cleaning: repeated header/footer removal, page-number removal, image-reference
  stripping, page markers as HTML comments.
- Chunking: heading-aware, token-budgeted (tiktoken o200k_base), tables kept
  intact; Docling documents use Docling's HybridChunker.
- Token estimates for raw output, cleaned Markdown, and every chunk.
- Result caching keyed on file hash, engine version, DocSift version, and options.
- `docsift compare`: run both engines on one document with a metrics report.
- CLI: `docsift convert` / `docsift compare` / `--engine` / `--max-tokens` /
  `--overlap` / `--no-cache`.
```

- [ ] **Step 3: Write the release workflow**

`.github/workflows/release.yml`:

```yaml
name: Release

on:
  release:
    types: [published]

permissions:
  contents: read

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - run: uv sync --locked --extra markitdown
      - run: uv run ruff check .
      - run: uv run pytest -v
      - run: uv build
      - run: uv publish --trusted-publishing always
```

- [ ] **Step 4: Update README**

Add after the compare section:

```markdown
## Chunking and cleaning

Conversion cleans the Markdown (repeated headers/footers, page numbers, image
references) and splits it into token-budgeted chunks with heading context:

    uv run docsift convert report.pdf --max-tokens 800 --overlap 100
    uv run docsift convert report.pdf --keep-image-refs
    uv run docsift convert report.pdf --no-cache

Results are cached in `~/.cache/docsift` (override with `DOCSIFT_CACHE_DIR`);
an unchanged file with unchanged settings returns instantly.
```

- [ ] **Step 5: Full verification — M3 exit criteria**

```bash
uv run pytest -v
uv run pytest tests/integration -m integration -v
uv run ruff check . && uv run ruff format --check .
uv build
uv run docsift convert tests/fixtures/multipage.pdf --output /tmp/docsift-m3 --max-tokens 300
uv run docsift convert tests/fixtures/multipage.pdf --output /tmp/docsift-m3 --max-tokens 300
uv run docsift convert tests/fixtures/table.pdf --output /tmp/docsift-m3b
```

Expected: suites green; `uv build` produces `dist/docsift-0.1.0-py3-none-any.whl` and sdist; first multipage convert reports chunks ≥ 2, second is instant with cached result (verify `"cached": true` in the JSON); table.pdf JSON contains an intact table chunk. Inspect `/tmp/docsift-m3/multipage.docsift.json`: every chunk has a stable ID, `section_path` and/or `pages`, and no chunk's text ends with a heading line.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/docsift/__init__.py CHANGELOG.md README.md .github/workflows/release.yml
git commit -m "chore: prepare v0.1.0 release (changelog, trusted-publishing workflow)"
```

*(Controller then: final whole-branch review → fix wave → push → CI → ask the user to set up the PyPI trusted publisher and publish the GitHub release.)*

---

## Self-review notes

- Spec coverage: FR-06 cleaning behaviors → Task 3 (each behavior has a named test); FR-07 chunking → Tasks 4 (fallback, all properties incl. heading-with-first-paragraph, table splitting with repeated headers, stable IDs, section path, pages) and 5 (HybridChunker preference per spec); FR-08 tiktoken + fallback + raw/cleaned/chunk counts → Tasks 1 and 6; FR-09 cache key = sha + config + engine version + docsift version → Task 7 (`test_key_varies_with_every_component`); v0.1 acceptance "cleaned Markdown / token-aware chunks / cache / no paid API / PyPI installable" → Tasks 6, 7, 8.
- M3 exit criteria are encoded as tests: heading-split prevention (`test_no_chunk_ends_with_a_heading`), tables intact (`test_small_table_stays_intact`, `test_oversized_table_splits_with_repeated_header`), stable IDs + metadata (`test_stable_ids_and_prefix`, `test_section_paths_follow_headings`, `test_pages_tracked_from_markers`), and verified end-to-end in Task 8 Step 5.
- Type consistency: `ConversionOptions`/`ChunkOptions`/`CleanOptions` defined once (Task 2) and consumed with identical names in Tasks 3–7; `estimate_tokens` signature frozen (Task 1) and used by Tasks 4, 5, 6; `EngineOutput.chunks: list[Chunk] | None` (Task 2) drives the Task 6 branch; `engine_impl.version()` (Task 2) feeds the Task 7 cache key.
- Known risk, mitigated: docling-core HybridChunker API drift — Task 5 carries an explicit verify-first + escalation clause, and the service treats `chunks=None` + warning as a fully supported degraded path, so v0.1 ships even if HybridChunker misbehaves.
- Deliberate scope holds: no `--engines` flag on compare, no schema_version bump (all additions are optional/defaulted), comparison bypasses cache by design.
