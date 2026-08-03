import re
from collections import Counter

from pydantic import BaseModel, Field

from docsift.core.options import CleanOptions

PAGE_BREAK = "<!-- page-break -->"
_PAGE_MARKER = re.compile(r"^<!-- page: \d+ -->$")
_PAGE_NUMBER = re.compile(r"^(page\s+)?\d+(\s+of\s+\d+)?$", re.IGNORECASE)
_IMAGE_REF = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")
_LIST_ITEM = re.compile(r"^[-*+] |^\d+[.)] ")
_FENCE = re.compile(r"^(`{3,}|~{3,})")


class CleanStats(BaseModel):
    duplicate_lines_removed: int = 0
    page_number_lines_removed: int = 0
    furniture_lines_removed: int = 0
    image_refs_removed: int = 0


class CleanPlan(BaseModel):
    """Removal decisions taken with whole-document context.

    Built once from the full Markdown so the same decisions can be applied to
    text derived from it. Engine-supplied chunks (Docling's HybridChunker builds
    them from its own structured document) never pass through `clean_markdown`,
    so without a plan they would keep the furniture the document-level clean
    removed.
    """

    furniture: tuple[str, ...] = ()
    options: CleanOptions = Field(default_factory=CleanOptions)


def _is_protected(stripped: str) -> bool:
    """Lines cleaning must never remove: headings, table rows, list items, page markers."""
    return (
        stripped.startswith("#")
        or stripped.startswith("|")
        or bool(_LIST_ITEM.match(stripped))
        or bool(_PAGE_MARKER.match(stripped))
    )


def mark_fences(lines: list[str]) -> list[tuple[str, bool]]:
    """Pair each line with True when it delimits or lives inside a fenced code block.

    Code samples and log excerpts legitimately contain repeated lines; every
    cleaning stage skips fenced content so it is never altered. Per CommonMark,
    a fence closes only on the same character with a run at least as long as the
    opener, so a `~~~` line inside a ``` block stays content rather than closing
    it, and a closing fence may not carry an info string.
    """
    marked: list[tuple[str, bool]] = []
    opener: tuple[str, int] | None = None
    for line in lines:
        stripped = line.strip()
        match = _FENCE.match(stripped)
        if match:
            run = match.group(1)
            trailing = stripped[len(run) :].strip()
            if opener is None:
                opener = (run[0], len(run))
            elif run[0] == opener[0] and len(run) >= opener[1] and not trailing:
                opener = None
            marked.append((line, True))
            continue
        marked.append((line, opener is not None))
    return marked


def _prepare(
    markdown: str, options: CleanOptions, stats: CleanStats
) -> tuple[list[tuple[str, bool, int]], set[int], int]:
    """Fence-mark, renumber pages, drop image refs and page numbers.

    Returns the surviving lines (each carrying its fenced flag and its index in
    the page-renumbered document), the indices that sit at a page boundary, and
    the page count.
    """
    marked = mark_fences([line.rstrip() for line in markdown.splitlines()])

    page = 1
    numbered: list[tuple[str, bool]] = []
    # Indices where a page boundary falls. Furniture removal only fires near
    # these, plus the very start/end of the document, since that is where real
    # running headers and footers live (FR-06). Recorded before markers are
    # dropped so adjacency still works with keep_page_markers=False.
    boundary_indices: set[int] = set()
    for line, fenced in marked:
        if not fenced and line.strip() == PAGE_BREAK:
            page += 1
            boundary_indices.add(len(numbered))
            if options.keep_page_markers:
                numbered.append((f"<!-- page: {page} -->", False))
            continue
        numbered.append((line, fenced))
    page_count = page
    if numbered:
        boundary_indices.add(0)
        boundary_indices.add(len(numbered) - 1)

    kept: list[tuple[str, bool, int]] = []
    for idx, (line, fenced) in enumerate(numbered):
        stripped = line.strip()
        if not fenced:
            if options.remove_image_refs and _IMAGE_REF.match(stripped):
                stats.image_refs_removed += 1
                continue
            if stripped and not _is_protected(stripped) and _PAGE_NUMBER.match(stripped):
                stats.page_number_lines_removed += 1
                continue
        kept.append((line, fenced, idx))
    return kept, boundary_indices, page_count


def _detect_furniture(
    indexed: list[tuple[str, bool, int]],
    boundary_indices: set[int],
    page_count: int,
    options: CleanOptions,
) -> set[str]:
    """Repeated short lines hugging page boundaries — running headers and footers."""
    if not options.remove_furniture or page_count <= 1:
        return set()
    threshold = max(options.furniture_min_repeats, page_count // 2)
    counts = Counter(
        line.strip()
        for line, fenced, idx in indexed
        if not fenced
        and 4 <= len(line.strip()) < 80
        and not _is_protected(line.strip())
        and _boundary_adjacent(idx, boundary_indices)
    )
    return {text for text, count in counts.items() if count >= threshold}


def _boundary_adjacent(idx: int, boundary_indices: set[int]) -> bool:
    return any(abs(idx - boundary) <= 3 for boundary in boundary_indices)


def _finish(marked: list[tuple[str, bool]], stats: CleanStats) -> str:
    """Collapse consecutive duplicates and blank runs, then join."""
    deduped: list[tuple[str, bool]] = []
    for line, fenced in marked:
        stripped = line.strip()
        if (
            not fenced
            and stripped
            and deduped
            and not deduped[-1][1]
            and deduped[-1][0].strip() == stripped
            and not _is_protected(stripped)
        ):
            stats.duplicate_lines_removed += 1
            continue
        deduped.append((line, fenced))

    collapsed: list[tuple[str, bool]] = []
    for line, fenced in deduped:
        if (
            not fenced
            and not line.strip()
            and collapsed
            and not collapsed[-1][1]
            and not collapsed[-1][0].strip()
        ):
            continue
        collapsed.append((line, fenced))
    while collapsed and not collapsed[0][0].strip():
        collapsed.pop(0)
    while collapsed and not collapsed[-1][0].strip():
        collapsed.pop()
    return "\n".join(line for line, _ in collapsed) + "\n"


def build_clean_plan(markdown: str, options: CleanOptions | None = None) -> CleanPlan:
    """Decide what to strip, using the whole document as context."""
    options = options or CleanOptions()
    indexed, boundary_indices, page_count = _prepare(markdown, options, CleanStats())
    furniture = _detect_furniture(indexed, boundary_indices, page_count, options)
    return CleanPlan(furniture=tuple(sorted(furniture)), options=options)


def clean_markdown(
    markdown: str,
    options: CleanOptions | None = None,
    plan: CleanPlan | None = None,
) -> tuple[str, CleanStats]:
    """Strip page furniture, page numbers and image refs from a whole document.

    Pass `plan` to reuse decisions already computed by `build_clean_plan`
    instead of re-detecting them.
    """
    options = options or (plan.options if plan else None) or CleanOptions()
    stats = CleanStats()
    indexed, boundary_indices, page_count = _prepare(markdown, options, stats)
    if not options.remove_furniture:
        furniture: set[str] = set()
    elif plan is not None:
        furniture = set(plan.furniture)
    else:
        furniture = _detect_furniture(indexed, boundary_indices, page_count, options)

    kept: list[tuple[str, bool]] = []
    for line, fenced, idx in indexed:
        if not fenced and line.strip() in furniture and _boundary_adjacent(idx, boundary_indices):
            stats.furniture_lines_removed += 1
            continue
        kept.append((line, fenced))
    return _finish(kept, stats), stats


def clean_excerpt(text: str, plan: CleanPlan) -> tuple[str, CleanStats]:
    """Apply a document's cleaning decisions to text derived from it.

    An excerpt carries no page structure, so planned furniture is removed
    wherever it appears rather than only near page boundaries. Pages are never
    renumbered — chunks record their pages in metadata.
    """
    options = plan.options
    stats = CleanStats()
    furniture = set(plan.furniture)
    marked = mark_fences([line.rstrip() for line in text.splitlines()])

    kept: list[tuple[str, bool]] = []
    for line, fenced in marked:
        stripped = line.strip()
        if not fenced:
            if stripped == PAGE_BREAK:
                # No stat bump: an excerpt has no page structure to renumber.
                continue
            if options.remove_image_refs and _IMAGE_REF.match(stripped):
                stats.image_refs_removed += 1
                continue
            if stripped and not _is_protected(stripped) and _PAGE_NUMBER.match(stripped):
                stats.page_number_lines_removed += 1
                continue
            if stripped in furniture:
                stats.furniture_lines_removed += 1
                continue
        kept.append((line, fenced))
    return _finish(kept, stats), stats
