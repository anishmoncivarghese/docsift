"""Local, token-budgeted retrieval over normalized document chunks."""

import sqlite3

from docsift.api.schemas import SearchResponse, SearchResult
from docsift.core.exceptions import SearchQueryError
from docsift.storage import database


def _normalize_query(query: str) -> str:
    """Collapse whitespace outside quoted phrases and trim the query."""
    normalized: list[str] = []
    quoted = False
    pending_space = False
    for character in query.strip():
        if character == '"':
            if pending_space and normalized and not quoted:
                normalized.append(" ")
            pending_space = False
            quoted = not quoted
            normalized.append(character)
        elif character.isspace() and not quoted:
            pending_space = True
        else:
            if pending_space and normalized:
                normalized.append(" ")
            pending_space = False
            normalized.append(character)
    return "".join(normalized)


_MAX_QUERY_LENGTH = 1024
_MAX_QUERY_TERMS = 64


def _validate_controls(limit: int, max_tokens: int, context: int) -> None:
    if not 1 <= limit <= 20:
        raise SearchQueryError("limit must be between 1 and 20")
    if not 1 <= max_tokens <= 20_000:
        raise SearchQueryError("max_tokens must be between 1 and 20000")
    if not 0 <= context <= 2:
        raise SearchQueryError("context must be between 0 and 2")


def _result_from_row(
    row: dict,
    *,
    match: bool,
    context_for: str | None,
    score: float | None,
) -> SearchResult:
    return SearchResult(
        chunk_id=row["chunk_id"],
        text=row["text"],
        estimated_tokens=row["estimated_tokens"],
        section_path=row["section_path"],
        pages=row["pages"],
        score=score,
        match=match,
        context_for=context_for,
    )


def search_document(
    document_id: str,
    query: str,
    *,
    limit: int = 5,
    max_tokens: int = 5000,
    context: int = 0,
) -> SearchResponse:
    """Return ranked direct matches plus optional adjacent chunks.

    `limit` applies to direct FTS matches. Context chunks can increase the
    result count, but every returned chunk shares one total token budget.
    """
    normalized_query = _normalize_query(query)
    if not normalized_query:
        raise SearchQueryError("query must not be blank")
    # Cost is quadratic in term count against SQLite FTS5, so bound both
    # length and term count before any query touches the database -- a
    # pasted page of text must fail cheaply, not after paying for the scan.
    if len(normalized_query) > _MAX_QUERY_LENGTH:
        raise SearchQueryError("query is too long")
    if len(normalized_query.split()) > _MAX_QUERY_TERMS:
        raise SearchQueryError("query has too many terms")
    _validate_controls(limit, max_tokens, context)

    try:
        direct_rows = database.search_document_chunks(document_id, normalized_query, limit)
    except sqlite3.OperationalError:
        # SQLite error text may repeat the caller's query. Keep the public
        # error stable and content-safe instead of exposing it.
        raise SearchQueryError("invalid search query") from None

    if not direct_rows:
        return SearchResponse(
            document_id=document_id,
            query=normalized_query,
            estimated_tokens=0,
        )

    direct_by_position = {row["position"]: row for row in direct_rows}
    if context:
        positions = sorted(
            {
                position
                for row in direct_rows
                for position in range(
                    max(0, row["position"] - context), row["position"] + context + 1
                )
            }
        )
        rows_by_position = {
            row["position"]: row for row in database.get_indexed_chunks(document_id, positions)
        }
    else:
        rows_by_position = direct_by_position

    candidates: list[SearchResult] = []
    seen: set[str] = set()
    for direct in direct_rows:
        start = max(0, direct["position"] - context)
        end = direct["position"] + context
        for position in range(start, end + 1):
            row = rows_by_position.get(position)
            if row is None or row["chunk_id"] in seen:
                continue
            direct_row = direct_by_position.get(position)
            is_match = direct_row is not None
            candidates.append(
                _result_from_row(
                    row,
                    match=is_match,
                    context_for=None if is_match else direct["chunk_id"],
                    score=direct_row["score"] if is_match else None,
                )
            )
            seen.add(row["chunk_id"])

    selected: list[SearchResult] = []
    used_tokens = 0
    for candidate in candidates:
        if used_tokens + candidate.estimated_tokens > max_tokens:
            break
        selected.append(candidate)
        used_tokens += candidate.estimated_tokens

    return SearchResponse(
        document_id=document_id,
        query=normalized_query,
        estimated_tokens=used_tokens,
        results=selected,
    )
