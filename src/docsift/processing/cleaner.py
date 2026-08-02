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
