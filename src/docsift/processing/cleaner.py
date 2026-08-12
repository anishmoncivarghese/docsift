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
_HEADING_LINE = re.compile(r"^#{1,6}\s+(.*)$")


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
    # Furniture whose every document occurrence sat at a page boundary, and which
    # is therefore safe to strip from derived text that carries no page structure
    # (an excerpt has no boundaries to gate a strip against, so anything that also
    # showed up mid-document must be left alone or a real body occurrence would be
    # deleted).
    excerpt_furniture: tuple[str, ...] = ()
    # The exact line strings the document-level clean removed as page numbers or
    # image references, excluding any string that also occurs inside a fence or
    # as a protected line anywhere in the document — so a chunk can never lose a
    # line the Markdown keeps.
    removed_lines: tuple[str, ...] = ()
    options: CleanOptions = Field(default_factory=CleanOptions)


def _is_protected(stripped: str) -> bool:
    """Lines cleaning must never remove: headings, table rows, list items, page markers."""
    return (
        stripped.startswith("#")
        or stripped.startswith("|")
        or bool(_LIST_ITEM.match(stripped))
        or bool(_PAGE_MARKER.match(stripped))
    )


def mark_fences_with_state(lines: list[str]) -> tuple[list[tuple[str, bool]], int | None]:
    """As `mark_fences`, plus the index of an opening fence that never closed.

    The cleaner treats an unterminated fence as running to EOF (CommonMark), but
    the chunker must not swallow the rest of the document into one atomic block,
    so it needs to know where the unclosed region starts.
    """
    marked: list[tuple[str, bool]] = []
    opener: tuple[str, int] | None = None
    opener_index: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        match = _FENCE.match(stripped)
        if match:
            run = match.group(1)
            trailing = stripped[len(run) :].strip()
            if opener is None:
                opener = (run[0], len(run))
                opener_index = idx
            elif run[0] == opener[0] and len(run) >= opener[1] and not trailing:
                opener = None
                opener_index = None
            marked.append((line, True))
            continue
        marked.append((line, opener is not None))
    return marked, opener_index


def mark_fences(lines: list[str]) -> list[tuple[str, bool]]:
    """Pair each line with True when it delimits or lives inside a fenced code block.

    Code samples and log excerpts legitimately contain repeated lines; every
    cleaning stage skips fenced content so it is never altered. Per CommonMark,
    a fence closes only on the same character with a run at least as long as the
    opener, so a `~~~` line inside a ``` block stays content rather than closing
    it, and a closing fence may not carry an info string. An unterminated fence
    (no closer at all) therefore runs to EOF — correct for the cleaner, whose
    fence exemption only needs to know "inside a fence or not"; the chunker
    needs more (see `mark_fences_with_state`), since treating the rest of the
    document as one atomic block would swallow every heading, table and page
    marker after the unclosed fence.
    """
    marked, _ = mark_fences_with_state(lines)
    return marked


def _prepare(
    markdown: str, options: CleanOptions, stats: CleanStats
) -> tuple[list[tuple[str, bool, int]], set[int], int, set[str]]:
    """Fence-mark, renumber pages, drop image refs and page numbers.

    Returns the surviving lines (each carrying its fenced flag and its index in
    the page-renumbered document), the indices that sit at a page boundary, the
    page count, and the stripped text of every line dropped as an image ref or
    page number (for `CleanPlan.removed_lines`).
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
        if not fenced and not options.keep_page_markers and _PAGE_MARKER.match(line.strip()):
            # An engine can supply these itself -- MarkItDown does, for slide
            # boundaries. Honour the option regardless of who wrote the marker,
            # or a deck would keep markers that a PDF drops.
            continue
        if not fenced and line.strip() == PAGE_BREAK:
            page += 1
            boundary_indices.add(len(numbered))
            if options.keep_page_markers:
                numbered.append((f"<!-- page: {page} -->", False))
            continue
        numbered.append((line, fenced))
    if options.keep_page_markers and page > 1:
        # Page 1 has no preceding break, so without this its content carries no
        # page attribution at all and the chunker cites it as page 2.
        numbered.insert(0, ("<!-- page: 1 -->", False))
        boundary_indices = {idx + 1 for idx in boundary_indices}
    page_count = page
    if numbered:
        boundary_indices.add(0)
        boundary_indices.add(len(numbered) - 1)

    kept: list[tuple[str, bool, int]] = []
    removed: set[str] = set()
    for idx, (line, fenced) in enumerate(numbered):
        stripped = line.strip()
        if not fenced:
            if options.remove_image_refs and _IMAGE_REF.match(stripped):
                stats.image_refs_removed += 1
                removed.add(stripped)
                continue
            if stripped and not _is_protected(stripped) and _PAGE_NUMBER.match(stripped):
                stats.page_number_lines_removed += 1
                removed.add(stripped)
                continue
        kept.append((line, fenced, idx))
    return kept, boundary_indices, page_count, removed


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


def _excerpt_safe_furniture(
    furniture: set[str],
    indexed: list[tuple[str, bool, int]],
    boundary_indices: set[int],
) -> set[str]:
    """Narrow `furniture` to strings that never occurred away from a boundary.

    `clean_excerpt` has no page structure to gate a strip against, so it can
    only remove a furniture string wherever it appears. That is only safe when
    every occurrence in the source document was itself boundary-adjacent — if
    the string ever showed up mid-document, that occurrence was real body text
    kept by `clean_markdown`, and an excerpt gives no way to distinguish it
    from the boundary occurrences.
    """
    non_boundary = {
        line.strip()
        for line, fenced, idx in indexed
        if not fenced and not _boundary_adjacent(idx, boundary_indices)
    }
    return furniture - non_boundary


def _dedupe_consecutive(
    marked: list[tuple[str, bool]], stats: CleanStats
) -> list[tuple[str, bool]]:
    """Collapse consecutive duplicate lines outside fences."""
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
    return deduped


def _collapse_blank_runs(marked: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Collapse consecutive blank lines outside fences and trim leading/trailing blanks."""
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
    return collapsed


def _finish(marked: list[tuple[str, bool]], stats: CleanStats) -> str:
    """Collapse consecutive duplicates and blank runs, then join."""
    deduped = _dedupe_consecutive(marked, stats)
    collapsed = _collapse_blank_runs(deduped)
    return "\n".join(line for line, _ in collapsed) + "\n"


def build_clean_plan(markdown: str, options: CleanOptions | None = None) -> CleanPlan:
    """Decide what to strip, using the whole document as context."""
    options = options or CleanOptions()
    indexed, boundary_indices, page_count, removed = _prepare(markdown, options, CleanStats())
    furniture = _detect_furniture(indexed, boundary_indices, page_count, options)
    excerpt_safe = _excerpt_safe_furniture(furniture, indexed, boundary_indices)

    # Docling's contextualize() prepends a chunk's heading path as plain,
    # unprefixed lines. When a running header repeats a section title, that
    # title also qualifies as furniture — but stripping it from a chunk would
    # delete exactly the context contextualize() exists to add. A string that
    # also occurs as a heading's title text anywhere in the document is never
    # excerpt-safe, even though it may still be safe to strip from the
    # Markdown itself (where the real heading line, prefixed with `#`, is
    # protected and untouched).
    heading_texts = {
        match.group(1).strip()
        for line in markdown.splitlines()
        if (match := _HEADING_LINE.match(line.strip()))
    }
    excerpt_safe -= heading_texts

    # A removed page-number/image-ref string is only safe to strip from a chunk
    # fragment wherever it appears if the document never also kept that exact
    # string somewhere a chunk fragment couldn't tell apart from the removed
    # occurrence — inside a fence (fragments can lose fence context entirely,
    # see clean_excerpt's docstring) or as a protected line (heading/table/list/
    # page marker, which cleaning never touches).
    unsafe = {
        line.strip()
        for line, fenced in mark_fences([ln.rstrip() for ln in markdown.splitlines()])
        if fenced or _is_protected(line.strip())
    }
    removed_lines = removed - unsafe
    return CleanPlan(
        furniture=tuple(sorted(furniture)),
        excerpt_furniture=tuple(sorted(excerpt_safe)),
        removed_lines=tuple(sorted(removed_lines)),
        options=options,
    )


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
    indexed, boundary_indices, page_count, _removed = _prepare(markdown, options, stats)
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

    Invariant: `clean_excerpt` may remove a line ONLY if the document-level
    clean already removed that exact line from the document. It never makes
    an independent removal decision.

    A chunk is not guaranteed to arrive with intact Markdown structure —
    Docling's `HybridChunker` can split an oversized item mid-fence, so an
    interior fragment of a long code/log block may carry no fence characters
    at all. Rule-based cleaning (regexes, consecutive-duplicate dedupe) fired
    on such a fragment would delete lines the document's own Markdown keeps
    intact, which is strictly worse than a chunk repeating a line. So this
    function is plan-driven, not rule-driven: it removes only
    - lines whose stripped text is in `plan.excerpt_furniture` (furniture
      whose every document occurrence was boundary-adjacent, so it is safe to
      strip wherever it appears in an excerpt with no page structure of its
      own), and
    - lines whose stripped text is in `plan.removed_lines` (page-number/
      image-ref lines the document-level clean removed, already excluding
      anything that also occurs inside a fence or as a protected line
      elsewhere in the document — see `build_clean_plan`),
    plus bare `PAGE_BREAK` marker lines (pages are never renumbered here;
    chunks record their pages in metadata). The fence exemption below is
    belt-and-braces: `plan.removed_lines` and `plan.excerpt_furniture` should
    already exclude fenced strings, but content inside a fence is never
    touched regardless.
    """
    stats = CleanStats()
    removable = set(plan.excerpt_furniture) | set(plan.removed_lines)
    marked = mark_fences([line.rstrip() for line in text.splitlines()])

    kept: list[tuple[str, bool]] = []
    for line, fenced in marked:
        stripped = line.strip()
        if not fenced:
            if stripped == PAGE_BREAK:
                # No stat bump: an excerpt has no page structure to renumber.
                continue
            if stripped in removable:
                if stripped in plan.excerpt_furniture:
                    stats.furniture_lines_removed += 1
                elif _PAGE_NUMBER.match(stripped):
                    stats.page_number_lines_removed += 1
                elif _IMAGE_REF.match(stripped):
                    stats.image_refs_removed += 1
                else:
                    stats.furniture_lines_removed += 1
                continue
        kept.append((line, fenced))
    collapsed = _collapse_blank_runs(kept)
    return "\n".join(line for line, _ in collapsed) + "\n", stats
