import re

from docsift.core.models import Chunk
from docsift.core.options import ChunkOptions
from docsift.processing.cleaner import mark_fences
from docsift.processing.token_estimator import estimate_tokens

_PAGE_MARKER = re.compile(r"^<!-- page: (\d+) -->$")
_HEADING = re.compile(r"^(#{1,6}) (.*)$")


def _block_text(block: dict) -> str:
    return "\n".join(block["lines"])


def _tokens(block: dict) -> int:
    return estimate_tokens(_block_text(block))


def _joined_tokens(blocks: list[dict]) -> int:
    """Token estimate of `blocks` as they will actually be emitted: joined with
    blank lines, not summed per-block. Summing per-block estimates undercounts
    (or overcounts) relative to tokenizing the real joined text, since the
    tokenizer doesn't split cleanly at block boundaries."""
    if not blocks:
        return 0
    return estimate_tokens("\n\n".join(_block_text(b) for b in blocks))


def _parse_blocks(markdown: str) -> list[dict]:
    """Split into heading/table/text/fenced blocks; track page from markers; drop markers."""
    blocks: list[dict] = []
    page: int | None = None
    heading_stack: list[tuple[int, str]] = []
    lines = markdown.splitlines()
    fenced = [flag for _, flag in mark_fences(lines)]
    i = 0
    while i < len(lines):
        if fenced[i]:
            # A code block is atomic: its `#` comments are not headings, its
            # pipes are not table rows, and splitting it would strand a fence.
            start = i
            while i < len(lines) and fenced[i]:
                i += 1
            blocks.append(
                {
                    "kind": "text",
                    "lines": lines[start:i],
                    "page": page,
                    "path": [t for _, t in heading_stack],
                }
            )
            continue
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
    if len(rows) < 2:
        # No separator row means this is not a real table; never treat a data
        # row as a header that gets repeated into every part. Behaviorally a
        # no-op today — `rows[2:]` is already empty for any `len(rows) <= 2`,
        # so the `if not body` fallback below already returns `[rows]` in
        # this case too. Kept as an explicit early return to document the
        # intent so a future edit to the body-slicing logic below doesn't
        # silently reintroduce header-duplication for a too-short table.
        return [rows]
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
    """Heading-aware, token-budgeted markdown chunker used when an engine
    does not supply its own chunks.

    Headings stay with their first paragraph (never the last block of a
    chunk, except when the document itself ends on a heading with no
    trailing body), tables stay intact unless oversized (split by rows,
    header repeated), and each chunk after the first carries an overlap
    tail from the previous chunk.

    Token budget guarantee: every chunk stays within ``max_tokens``
    EXCEPT when it contains at most one non-heading content block (a
    single paragraph or table part that cannot be sub-split), in which
    case that indivisible block — plus any headings that must stay
    attached to it — may push the chunk over ``max_tokens`` (bounded in
    practice by that one block's size plus the carried overlap). This is
    the deliberate cost of never orphaning a heading from its content or
    slicing a paragraph mid-sentence.
    """
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

    def flush(final: bool = False) -> None:
        nonlocal current
        if not current:
            return
        # Pop *every* trailing heading, not just one. If two or more headings
        # sit back to back at the end of `current` (e.g. "# A\n\n## B\n\n" with
        # nothing between them yet), popping only the last one would leave an
        # earlier heading as the new last block and emit a chunk that still
        # ends with a heading — violating the "no chunk ends with a heading"
        # exit criterion. Carrying all of them forward keeps the full nested
        # heading stack intact for whichever content block arrives next.
        #
        # Only do this mid-stream. On the terminal flush (`final=True`) there
        # is no "next content block" coming — carrying trailing headings out
        # would just re-stash them in `current` forever and silently drop
        # them when the caller stops calling flush(). If the document itself
        # ends on a heading, that heading legitimately becomes the last block
        # of the last chunk; a document must never lose content just because
        # its last line happens to be a heading.
        carried: list[dict] = []
        if not final:
            while current and current[-1]["kind"] == "heading":
                carried.insert(0, current.pop())
        content = [b for b in current if b["kind"] != "overlap"]
        if not content:
            current = list(carried)
            return
        text = "\n\n".join(_block_text(b) for b in current)
        pages = sorted({b["page"] for b in content if b["page"] is not None})
        # section_path is derived from the chunk's first non-heading (body)
        # block, not the first block overall and not the last block. Headings
        # sitting at the top of a chunk are scaffolding for the body that
        # follows, so the body is what establishes what the chunk is
        # actually about — using the first heading would under-report nested
        # context (e.g. "H1/H2/H3" collapsing to "H1"), and using the last
        # block would report where a multi-section chunk ended up rather
        # than what it's mostly about (e.g. a chunk that's mostly "Expenses"
        # content plus a trailing "Risks" heading would misreport as
        # "Risks"). Each block's `path` was captured at parse time from the
        # fully-resolved heading stack at that point, so the first body
        # block's path is already the deepest context under which that body
        # sits. Fall back to the last block (necessarily a heading) only for
        # the rare heading-only chunk, where no body block exists.
        body = [block for block in content if block["kind"] != "heading"]
        section_source = body[0] if body else content[-1]
        chunks.append(
            Chunk(
                chunk_id=f"{document_id}_c{len(chunks):03d}",
                text=text,
                estimated_tokens=estimate_tokens(text),
                section_path=list(section_source["path"]),
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
        current = overlap + carried

    for block in blocks:
        # Keep flushing (and, if needed, dropping a now-stale carried overlap)
        # until `current` can safely accept this block without stacking two
        # already-indivisible pieces (an overlap tail, a carried heading, an
        # oversized paragraph/table part) into one oversized chunk. A single
        # flush() call only removes one layer at a time — e.g. flushing real
        # content can leave behind an [overlap, carried-heading] pair that is
        # itself still over budget — so this must loop, not run once.
        #
        # The over-budget test always measures the actual "\n\n"-joined text
        # of `current + [block]`, not a sum of per-block token estimates:
        # summing undercounts (or overcounts) relative to tokenizing the real
        # joined text, since the tokenizer doesn't split cleanly at block
        # boundaries. That drift is what let chunks silently exceed
        # `max_tokens` by up to 5% before this fix.
        while True:
            has_content = any(b["kind"] != "overlap" for b in current)
            if has_content and _joined_tokens(current + [block]) > options.max_tokens:
                before = list(current)
                flush()
                if current == before:
                    # No progress: `current` was entirely headings (e.g. two
                    # or more back-to-back headings with no body yet), so
                    # flush() had no real content to emit and just handed the
                    # same headings back unchanged. Further flushing would
                    # loop forever — stop retrying and append this block,
                    # keeping the headings together with their first content
                    # even if that means exceeding max_tokens (the sanctioned
                    # "single indivisible block" exception applies to a run
                    # of headings plus the content that must stay with them).
                    break
                continue
            over_budget = _joined_tokens(current + [block]) > options.max_tokens
            if not has_content and current and over_budget:
                # `current` holds only a carried-over overlap tail (no real
                # content). Even that overlap alone plus this next block
                # would blow the budget — carrying an indivisible overlap
                # line forward and stacking another indivisible block on top
                # of it would combine two oversized blocks into one chunk,
                # which is not the sanctioned "single indivisible block"
                # exception. Drop the stale overlap instead of force-merging
                # it with the next block.
                current = []
            break
        current.append(block)
    flush(final=True)
    return chunks
