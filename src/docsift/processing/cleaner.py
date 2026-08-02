import re
from collections import Counter

from pydantic import BaseModel

from docsift.core.options import CleanOptions

PAGE_BREAK = "<!-- page-break -->"
_PAGE_MARKER = re.compile(r"^<!-- page: \d+ -->$")
_PAGE_NUMBER = re.compile(r"^(page\s+)?\d+(\s+of\s+\d+)?$", re.IGNORECASE)
_IMAGE_REF = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")
_LIST_ITEM = re.compile(r"^[-*+] |^\d+[.)] ")
_FENCE = re.compile(r"^(```|~~~)")


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
    cleaning stage skips fenced content so it is never altered.
    """
    marked: list[tuple[str, bool]] = []
    in_fence = False
    for line in lines:
        if _FENCE.match(line.strip()):
            marked.append((line, True))
            in_fence = not in_fence
            continue
        marked.append((line, in_fence))
    return marked


def clean_markdown(markdown: str, options: CleanOptions | None = None) -> tuple[str, CleanStats]:
    options = options or CleanOptions()
    stats = CleanStats()
    marked = _mark_fences([line.rstrip() for line in markdown.splitlines()])

    page = 1
    numbered: list[tuple[str, bool]] = []
    for line, fenced in marked:
        if not fenced and line.strip() == PAGE_BREAK:
            page += 1
            if options.keep_page_markers:
                numbered.append((f"<!-- page: {page} -->", False))
            continue
        numbered.append((line, fenced))
    marked = numbered

    kept: list[tuple[str, bool]] = []
    for line, fenced in marked:
        stripped = line.strip()
        if not fenced:
            if options.remove_image_refs and _IMAGE_REF.match(stripped):
                stats.image_refs_removed += 1
                continue
            if stripped and not _is_protected(stripped) and _PAGE_NUMBER.match(stripped):
                stats.page_number_lines_removed += 1
                continue
        kept.append((line, fenced))
    marked = kept

    if options.remove_furniture:
        candidates = Counter(
            line.strip()
            for line, fenced in marked
            if not fenced and 4 <= len(line.strip()) < 80 and not _is_protected(line.strip())
        )
        furniture = {
            text for text, count in candidates.items() if count >= options.furniture_min_repeats
        }
        kept = []
        for line, fenced in marked:
            if not fenced and line.strip() in furniture:
                stats.furniture_lines_removed += 1
                continue
            kept.append((line, fenced))
        marked = kept

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
