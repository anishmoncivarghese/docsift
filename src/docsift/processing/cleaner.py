import re
from collections import Counter

from pydantic import BaseModel

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


def _is_protected(stripped: str) -> bool:
    """Lines cleaning must never remove: headings, table rows, list items, page markers."""
    return (
        stripped.startswith("#")
        or stripped.startswith("|")
        or bool(_LIST_ITEM.match(stripped))
        or bool(_PAGE_MARKER.match(stripped))
    )


def _mark_fences(lines: list[str]) -> list[tuple[str, bool]]:
    """Pair each line with True when it delimits or lives inside a fenced code block.

    Code samples and log excerpts legitimately contain repeated lines; every
    cleaning stage skips fenced content so it is never altered. Per CommonMark,
    a fence closes only on the same character with a run at least as long as the
    opener, so a `~~~` line inside a ``` block stays content rather than closing it.
    A closing fence may not carry an info string, so ``` python inside an open block stays content.
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


def clean_markdown(markdown: str, options: CleanOptions | None = None) -> tuple[str, CleanStats]:
    options = options or CleanOptions()
    stats = CleanStats()
    marked = _mark_fences([line.rstrip() for line in markdown.splitlines()])

    page = 1
    numbered: list[tuple[str, bool]] = []
    # Positions (indices into `numbered`) that sit at a page boundary: where a
    # page-marker line was emitted, or — when markers are dropped — where the
    # next page's content begins. Furniture removal only fires near these, plus
    # the very start/end of the document, since that is where real running
    # headers and footers live (FR-06). Tracked before markers are dropped so
    # boundary-adjacency still works with keep_page_markers=False.
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

    indexed: list[tuple[str, bool, int]] = [
        (line, fenced, idx) for idx, (line, fenced) in enumerate(numbered)
    ]

    kept: list[tuple[str, bool, int]] = []
    for line, fenced, idx in indexed:
        stripped = line.strip()
        if not fenced:
            if options.remove_image_refs and _IMAGE_REF.match(stripped):
                stats.image_refs_removed += 1
                continue
            if stripped and not _is_protected(stripped) and _PAGE_NUMBER.match(stripped):
                stats.page_number_lines_removed += 1
                continue
        kept.append((line, fenced, idx))
    indexed = kept

    if options.remove_furniture and page_count > 1:
        threshold = max(options.furniture_min_repeats, page_count // 2)

        def _boundary_adjacent(idx: int) -> bool:
            return any(abs(idx - boundary) <= 3 for boundary in boundary_indices)

        candidates = Counter(
            line.strip()
            for line, fenced, idx in indexed
            if not fenced
            and 4 <= len(line.strip()) < 80
            and not _is_protected(line.strip())
            and _boundary_adjacent(idx)
        )
        furniture = {text for text, count in candidates.items() if count >= threshold}
        kept = []
        for line, fenced, idx in indexed:
            if not fenced and line.strip() in furniture and _boundary_adjacent(idx):
                stats.furniture_lines_removed += 1
                continue
            kept.append((line, fenced, idx))
        indexed = kept

    marked = [(line, fenced) for line, fenced, idx in indexed]

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
    marked = deduped

    collapsed: list[tuple[str, bool]] = []
    for line, fenced in marked:
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
    return "\n".join(line for line, _ in collapsed) + "\n", stats
