import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from docsift.core.config import get_settings
from docsift.core.models import Chunk

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    media_type  TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    engine      TEXT NOT NULL,
    result_path TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    document_id      TEXT,
    status           TEXT NOT NULL,
    error            TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

# Kept separate from _SCHEMA (and executed on its own) so a SQLite build
# without the FTS5 extension can fail creating just this table while the
# rest of init_db() still succeeds -- see init_db().
_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks USING fts5(
    document_id UNINDEXED,
    doc_token,
    chunk_id UNINDEXED,
    position UNINDEXED,
    section,
    section_path UNINDEXED,
    text,
    pages UNINDEXED,
    estimated_tokens UNINDEXED
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def database_path() -> Path:
    data_dir = get_settings().data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "docsift.db"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A fresh connection per use — no shared state, so worker threads are safe."""
    connection = sqlite3.connect(database_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        yield connection
        connection.commit()
    finally:
        connection.close()


def _rebuild_document_chunks_if_legacy(connection: sqlite3.Connection) -> None:
    """Drop a `document_chunks` FTS5 table built before `doc_token` existed.

    FTS5 virtual tables cannot be ALTERed to add a column, and the index is
    derived data -- every document is reindexed on its next conversion -- so
    the safe migration is to drop the stale table and let the
    `CREATE VIRTUAL TABLE IF NOT EXISTS` below recreate it with the current
    schema. A database that never had `document_chunks` at all (e.g. one
    from before search existed) has nothing to drop here; the same
    `CREATE ... IF NOT EXISTS` creates it fresh.
    """
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'document_chunks'"
    ).fetchone()
    if row is not None and row["sql"] is not None and "doc_token" not in row["sql"]:
        connection.execute("DROP TABLE document_chunks")


def init_db() -> None:
    with connect() as connection:
        connection.executescript(_SCHEMA)
        # CREATE TABLE IF NOT EXISTS above never adds columns to an existing
        # database, so a database created before `cancel_requested` existed
        # needs this migration run on top of it. Idempotent: the second and
        # later calls hit "duplicate column" and are ignored.
        try:
            connection.execute(
                "ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # column already present
        _rebuild_document_chunks_if_legacy(connection)
        try:
            connection.executescript(_FTS_SCHEMA)
        except sqlite3.OperationalError:
            # This SQLite build lacks the FTS5 extension. The schema above
            # already succeeded, so the rest of the service still starts;
            # search_index_available() reports the gap so the search path
            # can degrade explicitly instead of failing startup entirely.
            pass


def create_job(job_id: str, document_id: str | None) -> None:
    now = _now()
    with connect() as connection:
        connection.execute(
            "INSERT INTO jobs (job_id, document_id, status, error, created_at, updated_at)"
            " VALUES (?, ?, 'queued', NULL, ?, ?)",
            (job_id, document_id, now, now),
        )


_MAX_ERROR_LENGTH = 500


def set_job_status(
    job_id: str,
    status: str,
    document_id: str | None = None,
    error: str | None = None,
) -> None:
    # Defence in depth: error text can originate from caller-controlled input
    # (e.g. the `engine` form field echoed into EngineNotAvailableError), so
    # bound what gets written to sqlite and served back regardless of what
    # validation exists upstream.
    if error is not None and len(error) > _MAX_ERROR_LENGTH:
        error = error[:_MAX_ERROR_LENGTH]
    with connect() as connection:
        connection.execute(
            "UPDATE jobs SET status = ?, updated_at = ?,"
            " document_id = COALESCE(?, document_id),"
            " error = COALESCE(?, error)"
            " WHERE job_id = ?",
            (status, _now(), document_id, error, job_id),
        )


def request_cancel(document_id: str) -> int:
    """Flag unfinished jobs for `document_id` so their results are never stored.

    A delete issued while conversion is running must not be undone by the worker
    finishing afterwards, so the decision is recorded on the job rather than
    raced on the filesystem.
    """
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE jobs SET cancel_requested = 1, updated_at = ?"
            " WHERE document_id = ? AND status IN ('queued', 'processing')",
            (_now(), document_id),
        )
        return cursor.rowcount


def is_cancel_requested(job_id: str) -> bool:
    with connect() as connection:
        row = connection.execute(
            "SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    return bool(row["cancel_requested"]) if row else False


def get_job(job_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def fail_stale_jobs() -> int:
    """Mark unfinished jobs failed at startup.

    A queued or processing row that survives a restart belongs to a process that
    is gone; a job stuck in `processing` forever is worse than one honestly
    reported as failed.
    """
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE jobs SET status = 'failed', error = 'interrupted', updated_at = ?"
            " WHERE status IN ('queued', 'processing')",
            (_now(),),
        )
        return cursor.rowcount


def save_document(
    document_id: str,
    filename: str,
    media_type: str,
    size_bytes: int,
    sha256: str,
    engine: str,
    result_path: str,
) -> None:
    with connect() as connection:
        connection.execute(
            "INSERT INTO documents"
            " (document_id, filename, media_type, size_bytes, sha256, engine,"
            "  result_path, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(document_id) DO UPDATE SET"
            "  filename = excluded.filename, media_type = excluded.media_type,"
            "  size_bytes = excluded.size_bytes, sha256 = excluded.sha256,"
            "  engine = excluded.engine, result_path = excluded.result_path",
            (
                document_id,
                filename,
                media_type,
                size_bytes,
                sha256,
                engine,
                result_path,
                _now(),
            ),
        )


def get_document(document_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE document_id = ?", (document_id,)
        ).fetchone()
    return dict(row) if row else None


def _doc_token(document_id: str) -> str:
    """A single searchable FTS5 term identifying one document.

    Stripping the `doc_` prefix leaves the 12 hex characters, which tokenize
    as one term -- unlike `document_id` itself, which isn't indexed at all.
    """
    return document_id.removeprefix("doc_")


def index_document_chunks(document_id: str, chunks: list[Chunk]) -> None:
    """Atomically replace the searchable chunks for one document."""
    rows = [
        (
            document_id,
            _doc_token(document_id),
            chunk.chunk_id,
            position,
            " > ".join(chunk.section_path),
            json.dumps(chunk.section_path),
            chunk.text,
            json.dumps(chunk.pages),
            chunk.estimated_tokens,
        )
        for position, chunk in enumerate(chunks)
    ]
    try:
        with connect() as connection:
            connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
            connection.executemany(
                "INSERT INTO document_chunks"
                " (document_id, doc_token, chunk_id, position, section, section_path, text,"
                "  pages, estimated_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
    except sqlite3.OperationalError as exc:
        if "no such table: document_chunks" not in str(exc):
            raise
        # This SQLite build lacks FTS5, so document_chunks was never
        # created (see init_db()). Skip indexing rather than failing the
        # conversion job that called this -- search degrades to 503
        # instead.
        return


def _decode_chunk_row(row: sqlite3.Row, *, score: float | None = None) -> dict:
    result = dict(row)
    result["position"] = int(result["position"])
    result["section_path"] = json.loads(result["section_path"])
    result["pages"] = json.loads(result["pages"])
    result["estimated_tokens"] = int(result["estimated_tokens"])
    if score is not None:
        result["score"] = score
    return result


def search_document_chunks(document_id: str, query: str, limit: int) -> list[dict]:
    """Return direct FTS matches ordered by SQLite BM25 relevance.

    Without a `doc_token:` filter, FTS5 resolves MATCH across every row of
    every document before the `AND document_id = ?` clause below trims it --
    O(corpus), not O(one document). Folding the token into the MATCH
    expression itself lets FTS5's index narrow the candidate set up front.
    The user's query stays parenthesized so none of its own operators can
    escape the conjunction and widen the match beyond this document. The
    `AND document_id = ?` clause stays as a belt-and-braces guarantee -- it
    is the isolation property already verified independently of this
    optimization.
    """
    match_expression = f"doc_token:{_doc_token(document_id)} AND ({query})"
    with connect() as connection:
        rows = connection.execute(
            "SELECT document_id, chunk_id, position, section, section_path, text, pages,"
            " estimated_tokens, bm25(document_chunks) AS rank"
            " FROM document_chunks"
            " WHERE document_chunks MATCH ? AND document_id = ?"
            " ORDER BY rank, position LIMIT ?",
            (match_expression, document_id, limit),
        ).fetchall()
    return [_decode_chunk_row(row, score=-float(row["rank"])) for row in rows]


def get_indexed_chunks(document_id: str, positions: list[int]) -> list[dict]:
    """Return indexed chunks at the requested positions in document order."""
    if not positions:
        return []
    placeholders = ", ".join("?" for _ in positions)
    with connect() as connection:
        rows = connection.execute(
            "SELECT document_id, chunk_id, position, section, section_path, text, pages,"
            f" estimated_tokens FROM document_chunks WHERE document_id = ?"
            f" AND position IN ({placeholders}) ORDER BY position",
            (document_id, *positions),
        ).fetchall()
    return [_decode_chunk_row(row) for row in rows]


def search_index_available() -> bool:
    """Whether this SQLite build has the FTS5 extension search needs.

    False after init_db() caught an OperationalError creating
    `document_chunks` -- a SQLite compiled without FTS5. Cheap: a single
    indexed lookup against sqlite_master, not a query against the table
    itself (which wouldn't exist to query).
    """
    with connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'document_chunks'"
        ).fetchone()
    return row is not None


def count_indexed_chunks(document_id: str) -> int:
    """Cheap row count for one document's search index -- no content scan."""
    with connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM document_chunks WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    return int(row["count"])


def delete_document(document_id: str) -> bool:
    with connect() as connection:
        connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
        cursor = connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
        return cursor.rowcount > 0
