# DocSift M4: REST API and Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI service where a client uploads a document, gets a job id back immediately, polls until the job finishes, and retrieves the Markdown, chunks and result JSON — with SQLite metadata, filesystem artifacts, and an OpenAPI document a Power Platform connector can import.

**Architecture:** SQLite (`storage/database.py`) is the source of truth for job and document metadata; artifacts live on disk under a data directory (`storage/documents.py`), separate from the existing conversion cache. `services/job_service.py` runs conversions on a bounded thread pool and records every state transition in SQLite, so job state survives a request and stale `processing` rows are reconciled on startup. The FastAPI layer (`api/`) is thin: validate, enqueue, read. Engine imports stay lazy — importing the app must not pull in Docling.

**Tech Stack:** Adds FastAPI, Uvicorn and python-multipart behind a new `api` extra. SQLite via stdlib `sqlite3`. No other new dependencies.

## Global Constraints

- Everything from prior plans still binds: uv only; **lazy engine imports** (`docsift --help` works with no engines; the unit lane must not import docling — `tests/unit/test_lazy_imports.py` guards this and must be extended to cover new modules); no engine types outside `engines/`; **never log, print, store or return document contents in errors, warnings, logs or job records** (exception text is reduced to `type(exc).__name__`); conventional commits; integration tests marked and excluded by default.
- **CI parity is mandatory.** CI installs only the markitdown extra. `convert_document` must keep the order `_validate` → `select_engine_name` → `get_engine` → `build_source_metadata`. After any task touching the service, engines or API, run this and paste the result in the report:
  ```bash
  uv venv /tmp/ci-parity --python 3.12
  VIRTUAL_ENV=/tmp/ci-parity uv pip install -e '.[markitdown,api]' pytest fpdf2
  VIRTUAL_ENV=/tmp/ci-parity uv run --no-project pytest tests/unit -q
  ```
- **No test may touch the real `~/.cache/docsift` or the real `~/.local/share/docsift`.** Every test that converts or starts the API sets BOTH `DOCSIFT_CACHE_DIR` and `DOCSIFT_DATA_DIR` to a tmp_path. Verify before/after with `ls ~/.cache/docsift ~/.local/share/docsift 2>/dev/null | wc -l`.
- All 140 existing tests must keep passing. If an existing assertion would need weakening, STOP and report BLOCKED. Changing a test *fixture* to express the same intent under new rules is allowed and must be explained.
- **A test that passes against the unfixed code protects nothing.** For every new test, verify it genuinely fails before the implementation and report the RED evidence. This project has shipped tests that asserted true either way.
- Do NOT modify plan files. Do not push; the controller pushes. Stage only files you changed — never `git add -A`.
- Repo root: `/Users/anish/DocBridge/docsift`. HEAD at plan time: `a3bdc61`. Released: 0.1.1 on PyPI.

## Deliberately out of scope for M4

- `GET /v1/documents/{id}/search` — Milestone 5.
- `POST /v1/compare` — comparison runs both engines and takes minutes; it needs its own job type. Deferred to a later milestone; M4's exit criteria do not include it.
- The FR-13 "fast path" (returning a completed result inline for small documents). Clients always poll. YAGNI until a connector actually needs it.
- Authentication, rate limiting, multi-tenancy — PRD non-goals for v0.x.

---

### Task 1: API extra and runtime settings

**Files:**
- Modify: `pyproject.toml`
- Create: `src/docsift/core/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `core.config.Settings` (Pydantic model) with fields `data_dir: Path`, `max_upload_bytes: int = 52428800`, `job_workers: int = 2`, `job_timeout_seconds: int = 900`; and `get_settings() -> Settings` which reads environment variables **at call time** (never at import time, so tests can monkeypatch). Env vars: `DOCSIFT_DATA_DIR` (default `~/.local/share/docsift`), `DOCSIFT_MAX_UPLOAD_BYTES`, `DOCSIFT_JOB_WORKERS`, `DOCSIFT_JOB_TIMEOUT_SECONDS`.
- The data directory is deliberately separate from `DOCSIFT_CACHE_DIR`: the cache is disposable, this is the service's records.

- [ ] **Step 1: Add the dependency extra**

In `pyproject.toml` `[project.optional-dependencies]`, add:

```toml
api = ["fastapi>=0.115", "uvicorn[standard]>=0.30", "python-multipart>=0.0.9"]
```

and extend the `all` extra to `all = ["docsift[markitdown]", "docsift[docling]", "docsift[api]"]`.

Run `uv sync --all-extras` and confirm `uv run python -c "import fastapi, uvicorn, multipart; print('api deps ok')"` prints `api deps ok`.

- [ ] **Step 2: Write the failing test**

`tests/unit/test_config.py`:

```python
from pathlib import Path

from docsift.core.config import Settings, get_settings


def test_defaults_when_no_env(monkeypatch):
    for name in (
        "DOCSIFT_DATA_DIR",
        "DOCSIFT_MAX_UPLOAD_BYTES",
        "DOCSIFT_JOB_WORKERS",
        "DOCSIFT_JOB_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.data_dir == Path.home() / ".local" / "share" / "docsift"
    assert settings.max_upload_bytes == 50 * 1024 * 1024
    assert settings.job_workers == 2
    assert settings.job_timeout_seconds == 900


def test_env_overrides_are_read_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("DOCSIFT_JOB_WORKERS", "5")
    monkeypatch.setenv("DOCSIFT_JOB_TIMEOUT_SECONDS", "30")
    settings = get_settings()
    assert settings.data_dir == tmp_path / "data"
    assert settings.max_upload_bytes == 1024
    assert settings.job_workers == 5
    assert settings.job_timeout_seconds == 30


def test_get_settings_does_not_create_the_directory(monkeypatch, tmp_path):
    target = tmp_path / "never-created"
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(target))
    get_settings()
    assert not target.exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.core.config`.

- [ ] **Step 4: Implement**

`src/docsift/core/config.py`:

```python
import os
from pathlib import Path

from pydantic import BaseModel

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class Settings(BaseModel):
    """Runtime settings for the DocSift service.

    `data_dir` holds the service's records — the SQLite database and stored
    artifacts. It is deliberately separate from the conversion cache
    (`DOCSIFT_CACHE_DIR`), which is disposable.
    """

    data_dir: Path
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    job_workers: int = 2
    job_timeout_seconds: int = 900


def get_settings() -> Settings:
    """Read settings from the environment. Called per use, never cached at import."""
    override = os.environ.get("DOCSIFT_DATA_DIR")
    data_dir = Path(override) if override else Path.home() / ".local" / "share" / "docsift"
    return Settings(
        data_dir=data_dir,
        max_upload_bytes=int(os.environ.get("DOCSIFT_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)),
        job_workers=int(os.environ.get("DOCSIFT_JOB_WORKERS", 2)),
        job_timeout_seconds=int(os.environ.get("DOCSIFT_JOB_TIMEOUT_SECONDS", 900)),
    )
```

- [ ] **Step 5: Run the full gate**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: 143 passed, 7 deselected, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/docsift/core/config.py tests/unit/test_config.py
git commit -m "feat: add api extra and runtime settings"
```

---

### Task 2: SQLite metadata store

**Files:**
- Create: `src/docsift/storage/database.py`
- Test: `tests/unit/test_database.py`

**Interfaces:**
- Consumes: `get_settings()` (Task 1).
- Produces:
  - `database_path() -> Path` — `<data_dir>/docsift.db`, creating the data directory.
  - `connect()` — context manager yielding a `sqlite3.Connection` with `row_factory = sqlite3.Row` and WAL enabled; commits on clean exit, always closes. A fresh connection per use, so the store is thread-safe without shared state.
  - `init_db() -> None` — creates the `documents` and `jobs` tables if absent. Idempotent.
  - `create_job(job_id: str, document_id: str | None) -> None` — inserts a row with `status="queued"`.
  - `set_job_status(job_id: str, status: str, document_id: str | None = None, error: str | None = None) -> None` — updates status, optional document id and error, and `updated_at`.
  - `get_job(job_id: str) -> dict | None`
  - `fail_stale_jobs() -> int` — marks every `queued`/`processing` row `failed` with error `"interrupted"`, returns the count. Called at startup: those jobs died with the previous process, and a job stuck in `processing` forever is worse than one honestly reported as failed.
  - `save_document(document_id: str, filename: str, media_type: str, size_bytes: int, sha256: str, engine: str, result_path: str) -> None` — upsert by `document_id`.
  - `get_document(document_id: str) -> dict | None`
  - `delete_document(document_id: str) -> bool` — returns whether a row was removed.
- Job statuses are exactly: `queued`, `processing`, `succeeded`, `failed`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_database.py`:

```python
import pytest

from docsift.storage import database


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    database.init_db()


def test_job_lifecycle():
    database.create_job("job_1", None)
    job = database.get_job("job_1")
    assert job["status"] == "queued"
    assert job["document_id"] is None

    database.set_job_status("job_1", "processing")
    assert database.get_job("job_1")["status"] == "processing"

    database.set_job_status("job_1", "succeeded", document_id="doc_abc")
    job = database.get_job("job_1")
    assert job["status"] == "succeeded"
    assert job["document_id"] == "doc_abc"
    assert job["error"] is None


def test_failed_job_records_error_without_document():
    database.create_job("job_2", None)
    database.set_job_status("job_2", "failed", error="ConversionFailedError")
    job = database.get_job("job_2")
    assert job["status"] == "failed"
    assert job["error"] == "ConversionFailedError"


def test_get_job_returns_none_for_unknown_id():
    assert database.get_job("job_missing") is None


def test_fail_stale_jobs_marks_unfinished_work():
    database.create_job("job_q", None)
    database.create_job("job_p", None)
    database.set_job_status("job_p", "processing")
    database.create_job("job_done", None)
    database.set_job_status("job_done", "succeeded", document_id="doc_x")

    assert database.fail_stale_jobs() == 2
    assert database.get_job("job_q")["status"] == "failed"
    assert database.get_job("job_p")["status"] == "failed"
    assert database.get_job("job_p")["error"] == "interrupted"
    assert database.get_job("job_done")["status"] == "succeeded"


def test_document_upsert_and_delete():
    database.save_document(
        "doc_abc", "report.pdf", "application/pdf", 10, "a" * 64, "docling", "/tmp/r.json"
    )
    document = database.get_document("doc_abc")
    assert document["filename"] == "report.pdf"
    assert document["engine"] == "docling"

    database.save_document(
        "doc_abc", "renamed.pdf", "application/pdf", 10, "a" * 64, "docling", "/tmp/r.json"
    )
    assert database.get_document("doc_abc")["filename"] == "renamed.pdf"

    assert database.delete_document("doc_abc") is True
    assert database.get_document("doc_abc") is None
    assert database.delete_document("doc_abc") is False


def test_init_db_is_idempotent():
    database.init_db()
    database.init_db()
    database.create_job("job_3", None)
    assert database.get_job("job_3") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_database.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.storage.database`.

- [ ] **Step 3: Implement**

`src/docsift/storage/database.py`:

```python
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from docsift.core.config import get_settings

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
    job_id      TEXT PRIMARY KEY,
    document_id TEXT,
    status      TEXT NOT NULL,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
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


def init_db() -> None:
    with connect() as connection:
        connection.executescript(_SCHEMA)


def create_job(job_id: str, document_id: str | None) -> None:
    now = _now()
    with connect() as connection:
        connection.execute(
            "INSERT INTO jobs (job_id, document_id, status, error, created_at, updated_at)"
            " VALUES (?, ?, 'queued', NULL, ?, ?)",
            (job_id, document_id, now, now),
        )


def set_job_status(
    job_id: str,
    status: str,
    document_id: str | None = None,
    error: str | None = None,
) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE jobs SET status = ?, updated_at = ?,"
            " document_id = COALESCE(?, document_id),"
            " error = COALESCE(?, error)"
            " WHERE job_id = ?",
            (status, _now(), document_id, error, job_id),
        )


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


def delete_document(document_id: str) -> bool:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
        return cursor.rowcount > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_database.py -v && uv run ruff check .`
Expected: 6 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/storage/database.py tests/unit/test_database.py
git commit -m "feat: add sqlite metadata store for documents and jobs"
```

---

### Task 3: Artifact storage on disk

**Files:**
- Create: `src/docsift/storage/documents.py`
- Test: `tests/unit/test_document_storage.py`

**Interfaces:**
- Consumes: `get_settings()` (Task 1), `ConversionResult` from `core.models`.
- Produces:
  - `document_dir(document_id: str) -> Path` — `<data_dir>/documents/<document_id>`, created on demand. **Rejects any `document_id` that is not `doc_` followed by 12 lowercase hex characters**, raising `UnsupportedFileError`; this is the path-traversal gate (NFR-04), so a client-supplied id can never escape the data directory.
  - `store_result(result: ConversionResult) -> Path` — writes `result.json` and `document.md` into that directory, atomically (temp file + `os.replace`), and returns the path to `result.json`.
  - `load_result(document_id: str) -> ConversionResult | None` — `None` when absent or unparsable.
  - `delete_document_files(document_id: str) -> bool` — removes the directory tree, returns whether anything existed.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_document_storage.py`:

```python
from datetime import UTC, datetime

import pytest

from docsift.core.exceptions import UnsupportedFileError
from docsift.core.models import (
    ConversionMetadata,
    ConversionMetrics,
    ConversionResult,
    DocumentContent,
    SourceMetadata,
)
from docsift.storage import documents


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))


def _result(document_id: str = "doc_abc123def456") -> ConversionResult:
    now = datetime.now(UTC)
    return ConversionResult(
        document_id=document_id,
        source=SourceMetadata(
            filename="report.pdf",
            media_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
        ),
        conversion=ConversionMetadata(
            engine="markitdown",
            engine_version="1.0",
            docsift_version="0.1.1",
            selection_reason="test",
            started_at=now,
            completed_at=now,
            duration_ms=1,
        ),
        document=DocumentContent(markdown="# Title\n\nBody.\n"),
        metrics=ConversionMetrics(characters=16, words=3, estimated_tokens=5),
    )


def test_store_and_load_round_trip():
    stored = documents.store_result(_result())
    assert stored.name == "result.json"
    loaded = documents.load_result("doc_abc123def456")
    assert loaded == _result()


def test_markdown_is_written_alongside_the_result():
    documents.store_result(_result())
    markdown = documents.document_dir("doc_abc123def456") / "document.md"
    assert markdown.read_text(encoding="utf-8") == "# Title\n\nBody.\n"


def test_load_returns_none_for_unknown_document():
    assert documents.load_result("doc_000000000000") is None


def test_load_returns_none_for_corrupt_result():
    documents.store_result(_result())
    (documents.document_dir("doc_abc123def456") / "result.json").write_text(
        "{not json", encoding="utf-8"
    )
    assert documents.load_result("doc_abc123def456") is None


def test_delete_removes_everything():
    documents.store_result(_result())
    assert documents.delete_document_files("doc_abc123def456") is True
    assert not documents.document_dir("doc_abc123def456").exists()
    assert documents.delete_document_files("doc_abc123def456") is False


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../etc",
        "doc_../../etc",
        "doc_ABC123DEF456",
        "doc_abc",
        "doc_abc123def456/x",
        "",
        "doc_abc123def45g",
    ],
)
def test_malformed_document_ids_are_rejected(bad_id):
    with pytest.raises(UnsupportedFileError, match="invalid document id"):
        documents.document_dir(bad_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_document_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.storage.documents`.

- [ ] **Step 3: Implement**

`src/docsift/storage/documents.py`:

```python
import os
import re
import shutil
import tempfile
from pathlib import Path

from docsift.core.config import get_settings
from docsift.core.exceptions import UnsupportedFileError
from docsift.core.models import ConversionResult

_DOCUMENT_ID = re.compile(r"^doc_[0-9a-f]{12}$")


def document_dir(document_id: str) -> Path:
    """Directory holding one document's artifacts.

    The id is validated against DocSift's own `doc_{12 hex}` shape rather than
    sanitized, so a client-supplied value can never traverse out of the data
    directory (NFR-04).
    """
    if not _DOCUMENT_ID.match(document_id):
        raise UnsupportedFileError(f"invalid document id: {document_id!r}")
    directory = get_settings().data_dir / "documents" / document_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_atomic(path: Path, text: str) -> None:
    handle = tempfile.NamedTemporaryFile(
        "w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8"
    )
    try:
        handle.write(text)
        handle.close()
        os.replace(handle.name, path)
    except OSError:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise


def store_result(result: ConversionResult) -> Path:
    """Persist a conversion result and its Markdown. Returns the result.json path."""
    directory = document_dir(result.document_id)
    result_path = directory / "result.json"
    _write_atomic(directory / "document.md", result.document.markdown)
    _write_atomic(result_path, result.model_dump_json(indent=2))
    return result_path


def load_result(document_id: str) -> ConversionResult | None:
    """Stored result, or None when absent or unreadable."""
    result_path = document_dir(document_id) / "result.json"
    if not result_path.is_file():
        return None
    try:
        return ConversionResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def delete_document_files(document_id: str) -> bool:
    directory = document_dir(document_id)
    if not any(directory.iterdir()):
        directory.rmdir()
        return False
    shutil.rmtree(directory, ignore_errors=True)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_document_storage.py -v && uv run ruff check .`
Expected: 11 passed (5 + 6 parametrized), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/storage/documents.py tests/unit/test_document_storage.py
git commit -m "feat: add filesystem artifact storage with path-traversal guard"
```

---

### Task 4: Job service

**Files:**
- Create: `src/docsift/services/job_service.py`
- Modify: `src/docsift/core/models.py`
- Test: `tests/unit/test_job_service.py`

**Interfaces:**
- Consumes: `database` (Task 2), `documents` (Task 3), `get_settings()` (Task 1), `convert_document` from `services.conversion_service`.
- Produces:
  - `core.models.JobRecord(BaseModel)` with `job_id: str`, `status: str`, `document_id: str | None = None`, `error: str | None = None`, `created_at: str`, `updated_at: str`.
  - `services.job_service.submit(source_path: Path, filename: str, engine: str = "auto", options: ConversionOptions | None = None) -> tuple[str, str]` — returns `(job_id, document_id)`. Computes the document id up front from the file's SHA-256 (so the caller can return it in the 202 response before conversion finishes), records a queued job, and schedules the work. `job_id` is `"job_" + uuid4().hex[:16]`.
  - `services.job_service.get(job_id: str) -> JobRecord | None`
  - `services.job_service.startup() -> None` — `init_db()` then `fail_stale_jobs()`.
  - `services.job_service.shutdown() -> None` — shuts the executor down, waiting for in-flight work.
  - `services.job_service.reset_for_tests() -> None` — disposes the executor so a new one is built with current settings.
- The worker records `processing`, runs the conversion, stores the result, saves document metadata, and records `succeeded`. On `DocSiftError` it records `failed` with `str(exc)`; on anything else it records `failed` with `type(exc).__name__` only — **never the exception message**, which can quote document content.
- `source_path` is deleted by the worker when it finishes, success or failure: it is the temporary upload copy.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_job_service.py`:

```python
import time
from pathlib import Path

import pytest

from docsift.core.models import EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine
from docsift.services import job_service
from docsift.storage import database, documents


class OkEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    @classmethod
    def version(cls) -> str:
        return "9.9.9"

    def convert(self, path: Path, options=None) -> EngineOutput:
        return EngineOutput(markdown="# Job\n\nBody text.\n", engine_version="9.9.9")


class BoomEngine(OkEngine):
    def convert(self, path: Path, options=None) -> EngineOutput:
        raise ValueError("secret document content")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    job_service.reset_for_tests()
    job_service.startup()
    yield
    job_service.shutdown()
    job_service.reset_for_tests()


@pytest.fixture
def upload(tmp_path) -> Path:
    source = tmp_path / "upload.txt"
    source.write_text("hello world", encoding="utf-8")
    return source


def _await_job(job_id: str, timeout: float = 15.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = job_service.get(job_id)
        if record and record.status in ("succeeded", "failed"):
            return record.status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def test_successful_job_stores_the_document(upload):
    register_engine("markitdown", OkEngine)
    try:
        job_id, document_id = job_service.submit(upload, "upload.txt")
        assert job_id.startswith("job_")
        assert document_id.startswith("doc_")
        assert _await_job(job_id) == "succeeded"
    finally:
        unregister_engine("markitdown")
    record = job_service.get(job_id)
    assert record.document_id == document_id
    assert record.error is None
    assert documents.load_result(document_id) is not None
    assert database.get_document(document_id)["engine"] == "markitdown"


def test_failed_job_never_records_document_content(upload):
    register_engine("markitdown", BoomEngine)
    try:
        job_id, _ = job_service.submit(upload, "upload.txt")
        assert _await_job(job_id) == "failed"
    finally:
        unregister_engine("markitdown")
    record = job_service.get(job_id)
    assert "secret document content" not in (record.error or "")
    assert "ValueError" in (record.error or "")


def test_upload_copy_is_removed_after_the_job(upload):
    register_engine("markitdown", OkEngine)
    try:
        job_id, _ = job_service.submit(upload, "upload.txt")
        assert _await_job(job_id) == "succeeded"
    finally:
        unregister_engine("markitdown")
    assert not upload.exists()


def test_unknown_job_is_none():
    assert job_service.get("job_missing") is None


def test_startup_fails_jobs_left_behind_by_a_dead_process():
    database.create_job("job_orphan", None)
    database.set_job_status("job_orphan", "processing")
    job_service.startup()
    record = job_service.get("job_orphan")
    assert record.status == "failed"
    assert record.error == "interrupted"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_job_service.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.services.job_service`.

- [ ] **Step 3: Implement**

Add to `src/docsift/core/models.py`, after `InspectionResult`:

```python
class JobRecord(BaseModel):
    """State of one asynchronous conversion job."""

    job_id: str
    status: str
    document_id: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
```

Create `src/docsift/services/job_service.py`:

```python
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from docsift.core.config import get_settings
from docsift.core.exceptions import DocSiftError
from docsift.core.models import JobRecord
from docsift.core.options import ConversionOptions
from docsift.storage import database, documents

_executor: ThreadPoolExecutor | None = None


def _pool() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=get_settings().job_workers, thread_name_prefix="docsift-job"
        )
    return _executor


def reset_for_tests() -> None:
    """Drop the executor so the next submit builds one from current settings."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None


def startup() -> None:
    """Prepare the store and reconcile jobs abandoned by a previous process."""
    database.init_db()
    database.fail_stale_jobs()


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None


def _document_id_for(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"doc_{digest.hexdigest()[:12]}"


def _run(job_id: str, source_path: Path, engine: str, options: ConversionOptions) -> None:
    from docsift.services.conversion_service import convert_document

    database.set_job_status(job_id, "processing")
    try:
        result = convert_document(source_path, engine=engine, options=options)
        result_path = documents.store_result(result)
        database.save_document(
            document_id=result.document_id,
            filename=result.source.filename,
            media_type=result.source.media_type,
            size_bytes=result.source.size_bytes,
            sha256=result.source.sha256,
            engine=result.conversion.engine,
            result_path=str(result_path),
        )
        database.set_job_status(job_id, "succeeded", document_id=result.document_id)
    except DocSiftError as exc:
        # DocSift's own errors are content-safe by construction.
        database.set_job_status(job_id, "failed", error=str(exc))
    except Exception as exc:
        # Anything else may quote document content: record the type name only.
        database.set_job_status(job_id, "failed", error=type(exc).__name__)
    finally:
        source_path.unlink(missing_ok=True)


def submit(
    source_path: Path,
    filename: str,
    engine: str = "auto",
    options: ConversionOptions | None = None,
) -> tuple[str, str]:
    """Queue a conversion. Returns (job_id, document_id).

    The document id is derived from the file's content up front so the caller
    can hand it back with the 202 response, before conversion has run.
    """
    options = options or ConversionOptions()
    source_path = Path(source_path)
    document_id = _document_id_for(source_path)
    job_id = f"job_{uuid4().hex[:16]}"
    database.create_job(job_id, document_id)
    _pool().submit(_run, job_id, source_path, engine, options)
    return job_id, document_id


def get(job_id: str) -> JobRecord | None:
    row = database.get_job(job_id)
    return JobRecord(**row) if row else None
```

Note the `filename` parameter is accepted for interface stability with the API layer (Task 5 passes the client's name), but conversion derives the stored filename from the temporary file's own name — Task 5 is responsible for giving the temp file a safe name carrying the right suffix.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_job_service.py -v && uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: all pass. Then run the docling-free CI-parity check from Global Constraints and paste the result.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/core/models.py src/docsift/services/job_service.py tests/unit/test_job_service.py
git commit -m "feat: add background job service backed by sqlite"
```

---

### Task 5: FastAPI app, health, and upload

**Files:**
- Create: `src/docsift/api/__init__.py` (empty), `src/docsift/api/schemas.py`, `src/docsift/api/app.py`
- Test: `tests/unit/test_api_upload.py`

**Interfaces:**
- Consumes: `job_service` (Task 4), `get_settings()` (Task 1), `SUPPORTED_SUFFIXES` from `engines.router`.
- Produces:
  - `api.schemas`: `HealthResponse(status: str)`, `VersionResponse(version: str)`, `JobAccepted(job_id: str, document_id: str, status: str)`, `JobStatusResponse(job_id: str, status: str, document_id: str | None, error: str | None)`, `ErrorResponse(detail: str)`.
  - `api.app.create_app() -> FastAPI` and a module-level `app = create_app()` (what Uvicorn imports).
  - `GET /health` → 200 `{"status": "ok"}`.
  - `GET /version` → 200 `{"version": "<docsift version>"}`.
  - `POST /v1/documents` (multipart form: `file`, optional `engine` field defaulting to `auto`) → **202** `{"job_id", "document_id", "status": "queued"}`.
- `job_service.submit` raises `ServiceUnavailableError` when the service is shutting down; the upload route must translate that into **503**, not let it become a 500.
- Upload rules (NFR-04): reject an extension outside `SUPPORTED_SUFFIXES` with **415**; reject a body larger than `max_upload_bytes` with **413**, streaming to a temp file and aborting as soon as the limit is exceeded rather than reading it all into memory; reject an empty file with **400**. The client filename is never used as a path — only its suffix is taken, and the temp file is created by `tempfile` under the data directory's `uploads/`.
- Engine imports stay lazy: `api.app` must not import any engine module at import time.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_api_upload.py`:

```python
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from docsift import __version__  # noqa: E402
from docsift.core.models import EngineOutput  # noqa: E402
from docsift.engines.base import ConversionEngine  # noqa: E402
from docsift.engines.registry import register_engine, unregister_engine  # noqa: E402


class OkEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    @classmethod
    def version(cls) -> str:
        return "9.9.9"

    def convert(self, path: Path, options=None) -> EngineOutput:
        return EngineOutput(markdown="# Api\n\nBody text.\n", engine_version="9.9.9")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    from docsift.services import job_service

    job_service.reset_for_tests()
    yield
    job_service.shutdown()
    job_service.reset_for_tests()


@pytest.fixture
def client():
    from docsift.api.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def engine():
    register_engine("markitdown", OkEngine)
    yield
    unregister_engine("markitdown")


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version(client):
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": __version__}


def test_upload_is_accepted_and_returns_ids(client, engine):
    response = client.post(
        "/v1/documents", files={"file": ("note.txt", b"hello world", "text/plain")}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["job_id"].startswith("job_")
    assert body["document_id"].startswith("doc_")
    assert body["status"] == "queued"


def test_unsupported_extension_is_rejected(client, engine):
    response = client.post("/v1/documents", files={"file": ("movie.mp4", b"data", "video/mp4")})
    assert response.status_code == 415


def test_empty_upload_is_rejected(client, engine):
    response = client.post("/v1/documents", files={"file": ("note.txt", b"", "text/plain")})
    assert response.status_code == 400


def test_oversized_upload_is_rejected(client, engine, monkeypatch):
    monkeypatch.setenv("DOCSIFT_MAX_UPLOAD_BYTES", "10")
    response = client.post("/v1/documents", files={"file": ("note.txt", b"x" * 100, "text/plain")})
    assert response.status_code == 413


def test_client_filename_cannot_escape_the_data_directory(client, engine, tmp_path):
    response = client.post(
        "/v1/documents",
        files={"file": ("../../evil.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 202
    assert not (tmp_path / "evil.txt").exists()
    assert not Path("/tmp/evil.txt").exists()


def test_importing_the_app_pulls_no_engine_modules():
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import docsift.api.app\n"
        "banned = {'docling', 'markitdown', 'torch', 'transformers'}\n"
        "loaded = {m.split('.')[0] for m in sys.modules}\n"
        "sys.exit(1 if banned & loaded else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_api_upload.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.api`.

- [ ] **Step 3: Implement**

`src/docsift/api/schemas.py`:

```python
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class VersionResponse(BaseModel):
    version: str


class JobAccepted(BaseModel):
    job_id: str
    document_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    document_id: str | None = None
    error: str | None = None


class ErrorResponse(BaseModel):
    detail: str
```

`src/docsift/api/app.py`:

```python
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from docsift import __version__
from docsift.api.schemas import HealthResponse, JobAccepted, VersionResponse
from docsift.core.config import get_settings
from docsift.engines.router import SUPPORTED_SUFFIXES
from docsift.services import job_service

_CHUNK = 1 << 20


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    job_service.startup()
    yield
    job_service.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="DocSift",
        version=__version__,
        summary="Convert documents once. Give agents only what they need.",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse, operation_id="getHealth")
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/version", response_model=VersionResponse, operation_id="getVersion")
    def version() -> VersionResponse:
        return VersionResponse(version=__version__)

    @app.post(
        "/v1/documents",
        response_model=JobAccepted,
        status_code=202,
        operation_id="uploadDocument",
    )
    async def upload_document(
        file: UploadFile = File(...),
        engine: str = Form("auto"),
    ) -> JobAccepted:
        settings = get_settings()
        # Only the suffix of the client's filename is ever used; the name itself
        # never becomes a path component, so `../../evil.txt` cannot escape.
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=415,
                detail=f"unsupported file type '{suffix}'",
            )

        uploads = settings.data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=uploads, suffix=suffix, delete=False)
        target = Path(handle.name)
        written = 0
        try:
            while block := await file.read(_CHUNK):
                written += len(block)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"upload exceeds {settings.max_upload_bytes} bytes",
                    )
                handle.write(block)
            handle.close()
            if written == 0:
                raise HTTPException(status_code=400, detail="uploaded file is empty")
        except HTTPException:
            handle.close()
            target.unlink(missing_ok=True)
            raise

        job_id, document_id = job_service.submit(
            target, file.filename or target.name, engine=engine
        )
        return JobAccepted(job_id=job_id, document_id=document_id, status="queued")

    return app


app = create_app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_api_upload.py -v && uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: all pass. Then the docling-free CI-parity run.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/api tests/unit/test_api_upload.py
git commit -m "feat: add fastapi app with health, version and async upload"
```

---

### Task 6: Job status and document retrieval endpoints

**Files:**
- Modify: `src/docsift/api/app.py`, `src/docsift/api/schemas.py`
- Test: `tests/unit/test_api_documents.py`

**Interfaces:**
- Consumes: `job_service.get` (Task 4), `documents.load_result`/`delete_document_files` (Task 3), `database.get_document`/`delete_document` (Task 2).
- Produces:
  - `GET /v1/jobs/{job_id}` → 200 `JobStatusResponse`, 404 when unknown. **`document_id` is the content address of the uploaded file and is present even on a failed job** — it is assigned at submission, before conversion runs. Clients must check `status == "succeeded"` before fetching it. Say so in the `JobStatusResponse.document_id` field description so the statement lands in `/openapi.json`, where connector builders read it, and add a test asserting a failed job still carries a `document_id` while its status is `failed` — that pins the contract instead of leaving it to be discovered.
  - `GET /v1/documents/{document_id}` → 200 the full `ConversionResult` JSON, 404 when unknown.
  - `GET /v1/documents/{document_id}/markdown` → 200 `text/markdown` plain body, 404 when unknown.
  - `GET /v1/documents/{document_id}/chunks` → 200 `{"document_id": str, "chunks": [...]}`, 404 when unknown.
  - `DELETE /v1/documents/{document_id}` → 204 on success, 404 when unknown. Removes both the database row and the artifact directory.
  - A malformed document id yields **404**, not a 500 — `documents.document_dir` raises `UnsupportedFileError` for anything that is not `doc_{12 hex}`, and the route translates that into 404 (the resource cannot exist).
  - New schema `ChunksResponse(document_id: str, chunks: list[Chunk])`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_api_documents.py`:

```python
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from docsift.core.models import EngineOutput  # noqa: E402
from docsift.engines.base import ConversionEngine  # noqa: E402
from docsift.engines.registry import register_engine, unregister_engine  # noqa: E402


class OkEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    @classmethod
    def version(cls) -> str:
        return "9.9.9"

    def convert(self, path: Path, options=None) -> EngineOutput:
        return EngineOutput(markdown="# Api\n\nBody paragraph text.\n", engine_version="9.9.9")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    from docsift.services import job_service

    job_service.reset_for_tests()
    yield
    job_service.shutdown()
    job_service.reset_for_tests()


@pytest.fixture
def client():
    from docsift.api.app import create_app

    register_engine("markitdown", OkEngine)
    with TestClient(create_app()) as test_client:
        yield test_client
    unregister_engine("markitdown")


def _upload_and_wait(client, timeout: float = 15.0) -> tuple[str, str]:
    response = client.post(
        "/v1/documents", files={"file": ("note.txt", b"hello world", "text/plain")}
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    document_id = response.json()["document_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/v1/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            assert status == "succeeded", client.get(f"/v1/jobs/{job_id}").json()
            return job_id, document_id
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_job_status_is_pollable_to_completion(client):
    job_id, document_id = _upload_and_wait(client)
    body = client.get(f"/v1/jobs/{job_id}").json()
    assert body["status"] == "succeeded"
    assert body["document_id"] == document_id
    assert body["error"] is None


def test_unknown_job_is_404(client):
    assert client.get("/v1/jobs/job_missing").status_code == 404


def test_document_result_is_retrievable(client):
    _, document_id = _upload_and_wait(client)
    response = client.get(f"/v1/documents/{document_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == document_id
    assert body["conversion"]["engine"] == "markitdown"


def test_markdown_is_retrievable_as_text(client):
    _, document_id = _upload_and_wait(client)
    response = client.get(f"/v1/documents/{document_id}/markdown")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# Api")


def test_chunks_are_retrievable(client):
    _, document_id = _upload_and_wait(client)
    response = client.get(f"/v1/documents/{document_id}/chunks")
    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == document_id
    assert len(body["chunks"]) >= 1
    assert body["chunks"][0]["chunk_id"].startswith(document_id)


def test_delete_removes_document_and_artifacts(client):
    _, document_id = _upload_and_wait(client)
    assert client.delete(f"/v1/documents/{document_id}").status_code == 204
    assert client.get(f"/v1/documents/{document_id}").status_code == 404
    assert client.delete(f"/v1/documents/{document_id}").status_code == 404


def test_unknown_document_is_404(client):
    assert client.get("/v1/documents/doc_000000000000").status_code == 404
    assert client.get("/v1/documents/doc_000000000000/markdown").status_code == 404
    assert client.get("/v1/documents/doc_000000000000/chunks").status_code == 404


@pytest.mark.parametrize("bad_id", ["not-a-doc-id", "doc_ABCDEF123456", "doc_short"])
def test_malformed_document_id_is_404_not_500(client, bad_id):
    assert client.get(f"/v1/documents/{bad_id}").status_code == 404


def test_reuploading_the_same_file_returns_the_same_document(client):
    _, first = _upload_and_wait(client)
    _, second = _upload_and_wait(client)
    assert first == second
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_api_documents.py -v`
Expected: FAIL — the job and document routes return 404 because they do not exist yet.

- [ ] **Step 3: Implement**

Add to `src/docsift/api/schemas.py`:

```python
from docsift.core.models import Chunk


class ChunksResponse(BaseModel):
    document_id: str
    chunks: list[Chunk]
```

In `src/docsift/api/app.py`, extend the imports:

```python
from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile

from docsift.api.schemas import (
    ChunksResponse,
    HealthResponse,
    JobAccepted,
    JobStatusResponse,
    VersionResponse,
)
from docsift.core.exceptions import UnsupportedFileError
from docsift.core.models import ConversionResult
from docsift.storage import database, documents
```

and add these routes inside `create_app()`, after `upload_document`:

```python
def _load_or_404(document_id: str) -> ConversionResult:
    try:
        result = documents.load_result(document_id)
    except UnsupportedFileError:
        # A malformed id names a resource that cannot exist.
        raise HTTPException(status_code=404, detail="document not found") from None
    if result is None:
        raise HTTPException(status_code=404, detail="document not found")
    return result


@app.get(
    "/v1/jobs/{job_id}",
    response_model=JobStatusResponse,
    operation_id="getJobStatus",
)
def get_job(job_id: str) -> JobStatusResponse:
    record = job_service.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        document_id=record.document_id,
        error=record.error,
    )


@app.get(
    "/v1/documents/{document_id}",
    response_model=ConversionResult,
    operation_id="getDocument",
)
def get_document(document_id: str) -> ConversionResult:
    return _load_or_404(document_id)


@app.get(
    "/v1/documents/{document_id}/markdown",
    response_class=Response,
    operation_id="getDocumentMarkdown",
)
def get_document_markdown(document_id: str) -> Response:
    result = _load_or_404(document_id)
    return Response(content=result.document.markdown, media_type="text/markdown; charset=utf-8")


@app.get(
    "/v1/documents/{document_id}/chunks",
    response_model=ChunksResponse,
    operation_id="getDocumentChunks",
)
def get_document_chunks(document_id: str) -> ChunksResponse:
    result = _load_or_404(document_id)
    return ChunksResponse(document_id=result.document_id, chunks=result.chunks)


@app.delete(
    "/v1/documents/{document_id}",
    status_code=204,
    operation_id="deleteDocument",
)
def delete_document(document_id: str) -> Response:
    try:
        removed_files = documents.delete_document_files(document_id)
    except UnsupportedFileError:
        raise HTTPException(status_code=404, detail="document not found") from None
    removed_row = database.delete_document(document_id)
    if not (removed_files or removed_row):
        raise HTTPException(status_code=404, detail="document not found")
    return Response(status_code=204)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_api_documents.py -v && uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: all pass. Then the docling-free CI-parity run.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/api tests/unit/test_api_documents.py
git commit -m "feat: add job status and document retrieval endpoints"
```

---

### Task 7: `docsift serve` and the OpenAPI document

**Files:**
- Modify: `src/docsift/cli/main.py`
- Create: `tests/unit/test_api_openapi.py`
- Modify: `tests/unit/test_lazy_imports.py`, `.github/workflows/ci.yml`

**CI gap to close in this task:** `.github/workflows/ci.yml` installs `uv sync --locked --extra markitdown`, so `fastapi` is absent and every API test module silently skips via `pytest.importorskip("fastapi")` — the entire HTTP surface would be untested in CI. Change that line to `uv sync --locked --extra markitdown --extra api`. Verify afterwards that a docling-free environment with the api extra actually *runs* the API tests rather than skipping them: `VIRTUAL_ENV=/tmp/ci-parity uv run --no-project pytest tests/unit -q` must report zero skips for `test_api_*`.

**Interfaces:**
- Consumes: `api.app` (Tasks 5–6).
- Produces:
  - `docsift serve [--host 127.0.0.1] [--port 8000] [--reload]` — imports uvicorn **inside the command function** and exits 1 with a clear install hint (`pip install 'docsift[api]'`) when the api extra is missing.
  - Verified OpenAPI properties: every route carries a stable `operationId` (Power Platform derives connector action names from them), and the document is retrievable at `/openapi.json`.
  - `tests/unit/test_lazy_imports.py` gains `docsift.api.app` and `docsift.services.job_service` to the probe list.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_api_openapi.py`:

```python
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from docsift.api.app import create_app  # noqa: E402

EXPECTED_OPERATIONS = {
    "getHealth",
    "getVersion",
    "uploadDocument",
    "getJobStatus",
    "getDocument",
    "getDocumentMarkdown",
    "getDocumentChunks",
    "deleteDocument",
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))


def test_openapi_document_is_served():
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "DocSift"


def test_every_operation_has_a_stable_id():
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()
    found = {
        operation["operationId"]
        for path in document["paths"].values()
        for operation in path.values()
        if "operationId" in operation
    }
    assert EXPECTED_OPERATIONS <= found


def test_upload_is_documented_as_accepted_not_ok():
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()
    assert "202" in document["paths"]["/v1/documents"]["post"]["responses"]


def test_serve_command_exists():
    from typer.testing import CliRunner

    from docsift.cli.main import app

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_api_openapi.py -v`
Expected: `test_serve_command_exists` FAILS (no such command); the OpenAPI tests pass if Tasks 5–6 set `operation_id` correctly — if any expected operation id is missing, fix the route decorator, not the test.

- [ ] **Step 3: Implement**

Add to `src/docsift/cli/main.py`, after the `compare` command:

```python
@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Interface to bind."),
    port: int = typer.Option(8000, help="Port to listen on."),
    reload: bool = typer.Option(False, "--reload", help="Reload on code changes."),
) -> None:
    """Run the DocSift HTTP API."""
    try:
        import uvicorn
    except ImportError as exc:
        typer.secho(
            "error: the API extra is not installed; install it with: pip install 'docsift[api]'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    uvicorn.run("docsift.api.app:app", host=host, port=port, reload=reload)
```

In `tests/unit/test_lazy_imports.py`, add both new modules to the probe's import list:

```python
"import docsift.api.app\n"

"import docsift.services.job_service\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_api_openapi.py tests/unit/test_lazy_imports.py -v && uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/cli/main.py tests/unit/test_api_openapi.py tests/unit/test_lazy_imports.py
git commit -m "feat: add docsift serve and pin stable openapi operation ids"
```

---

### Task 8: Docker, docs, and M4 exit verification

**Files:**
- Create: `Dockerfile`, `.dockerignore`
- Modify: `README.md`, `CHANGELOG.md`, `pyproject.toml`, `src/docsift/__init__.py`

**Interfaces:**
- Consumes: everything above.
- Produces: a container image running the API as a **non-root user** (NFR-04), README API documentation, a 0.2.0 changelog entry, and verified M4 exit criteria.
- Version becomes `0.2.0` — this adds a feature surface, not a patch.

- [ ] **Step 1: Write the Dockerfile**

`Dockerfile`:

```dockerfile
FROM python:3.12-slim

# uv installs dependencies; the image runs the API as a non-root user (NFR-04).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --locked --extra markitdown --extra api --no-dev

RUN useradd --create-home --uid 10001 docsift \
    && mkdir -p /data \
    && chown -R docsift:docsift /app /data
USER docsift

ENV DOCSIFT_DATA_DIR=/data \
    DOCSIFT_CACHE_DIR=/data/cache \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "docsift.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

`.dockerignore`:

```gitignore
.git
.github
.venv
.superpowers
.code-review-graph
benchmarks/corpus
dist
docs
tests
output
__pycache__
*.pyc
```

- [ ] **Step 2: Bump the version and write the changelog**

`pyproject.toml`: `version = "0.2.0"`. `src/docsift/__init__.py`: `__version__ = "0.2.0"`. Run `uv sync`.

Insert above the 0.1.1 entry in `CHANGELOG.md`:

```markdown
## 0.2.0 — 2026-08-05

Adds an HTTP API.

- `docsift serve` runs a FastAPI service (install with `pip install "docsift[api]"`).
- `POST /v1/documents` accepts an upload and returns `202` with a job id and a
  document id immediately; conversion runs in the background. Clients poll
  `GET /v1/jobs/{job_id}` until the status is `succeeded` or `failed`. The API is
  asynchronous by design: Docling on a long PDF routinely exceeds the ~120-second
  timeout that Power Platform custom connectors enforce.
- `GET /v1/documents/{id}`, `/markdown` and `/chunks` retrieve the result;
  `DELETE /v1/documents/{id}` removes it and its stored files.
- Job and document metadata live in SQLite under `DOCSIFT_DATA_DIR`
  (default `~/.local/share/docsift`), separate from the disposable conversion
  cache in `DOCSIFT_CACHE_DIR`.
- Jobs left `queued` or `processing` by a stopped process are reported as
  `failed` with error `interrupted` on the next startup rather than hanging.
- Uploads are capped at 50 MB (`DOCSIFT_MAX_UPLOAD_BYTES`), unsupported types are
  rejected with `415`, and the client's filename is never used as a path.
- A `Dockerfile` runs the service as a non-root user.
- OpenAPI at `/openapi.json`, with stable operation ids for connector imports.

Search (`/v1/documents/{id}/search`) and `POST /v1/compare` are not implemented yet.
```

- [ ] **Step 3: Document the API in the README**

Add after the existing usage section:

```markdown
## HTTP API

    pip install "docsift[api]"
    docsift serve

Then convert a document asynchronously:

    # returns 202 with {"job_id": "...", "document_id": "...", "status": "queued"}
    curl -sS -F file=@report.pdf http://127.0.0.1:8000/v1/documents

    # poll until "succeeded" or "failed"
    curl -sS http://127.0.0.1:8000/v1/jobs/job_xxxxxxxxxxxxxxxx

    # then fetch the result
    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/markdown
    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/chunks

Conversion always runs in the background — a long PDF can take minutes, and
clients that assume a synchronous response will time out. The OpenAPI document
is at `/openapi.json`.

State lives in `DOCSIFT_DATA_DIR` (default `~/.local/share/docsift`): a SQLite
database of jobs and documents, plus stored artifacts. Uploads are capped at
50 MB via `DOCSIFT_MAX_UPLOAD_BYTES`.

**Running untrusted documents:** the service converts whatever it is given.
Run it on infrastructure you control, behind your own authentication — DocSift
has none of its own — and prefer the container, which runs as a non-root user.
```

Also extend the Known limitations section with:

```markdown
- The API has no authentication, rate limiting or multi-tenancy. Do not expose
  it directly to the internet.
- Search and comparison endpoints are not implemented yet.
```

- [ ] **Step 4: Verify the M4 exit criteria end to end with real engines**

Start the service against a scratch data directory and drive it with `curl` exactly as the PRD's exit criteria describe:

```bash
export DOCSIFT_DATA_DIR=/tmp/m4-data DOCSIFT_CACHE_DIR=/tmp/m4-cache
uv run docsift serve --port 8765 &
sleep 3
curl -sS http://127.0.0.1:8765/health
JOB=$(curl -sS -F file=@tests/fixtures/multipage.pdf http://127.0.0.1:8765/v1/documents)
echo "$JOB"
JOB_ID=$(echo "$JOB" | uv run python -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
DOC_ID=$(echo "$JOB" | uv run python -c "import json,sys; print(json.load(sys.stdin)['document_id'])")
until [ "$(curl -sS http://127.0.0.1:8765/v1/jobs/$JOB_ID | uv run python -c 'import json,sys; print(json.load(sys.stdin)["status"])')" != "queued" ] \
   && [ "$(curl -sS http://127.0.0.1:8765/v1/jobs/$JOB_ID | uv run python -c 'import json,sys; print(json.load(sys.stdin)["status"])')" != "processing" ]; do sleep 2; done
curl -sS http://127.0.0.1:8765/v1/jobs/$JOB_ID
curl -sS -o /dev/null -w "markdown:%{http_code}\n" http://127.0.0.1:8765/v1/documents/$DOC_ID/markdown
curl -sS http://127.0.0.1:8765/v1/documents/$DOC_ID/chunks | uv run python -c "import json,sys; print('chunks:', len(json.load(sys.stdin)['chunks']))"
curl -sS -o /dev/null -w "reupload:%{http_code}\n" -F file=@tests/fixtures/multipage.pdf http://127.0.0.1:8765/v1/documents
curl -sS -o /dev/null -w "delete:%{http_code}\n" -X DELETE http://127.0.0.1:8765/v1/documents/$DOC_ID
curl -sS -o /dev/null -w "after-delete:%{http_code}\n" http://127.0.0.1:8765/v1/documents/$DOC_ID
kill %1
```

Expected: health `{"status":"ok"}`; upload returns a job id and document id; the job reaches `succeeded`; markdown 200; chunks ≥ 1; re-upload returns 202 with the **same** document id and completes near-instantly from cache; delete 204; the subsequent fetch 404. Report the observed values and timings — **metrics only, never document text**.

- [ ] **Step 5: Run every gate**

```bash
uv run pytest -v
uv run pytest tests/integration -m integration -v
uv run ruff check . && uv run ruff format --check .
uv build
tar -tzf dist/docsift-0.2.0.tar.gz | grep -E 'superpowers|code-review-graph|CLAUDE' && echo LEAK || echo "sdist clean"
```

plus the docling-free CI-parity run from Global Constraints. Confirm neither `~/.cache/docsift` nor `~/.local/share/docsift` was touched by the suite.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile .dockerignore README.md CHANGELOG.md pyproject.toml uv.lock src/docsift/__init__.py
git commit -m "chore: add container image, API docs, and prepare v0.2.0"
```

*(Controller then runs the whole-branch review, pushes, confirms CI, and asks about publishing.)*

---

## Self-review notes

- Exit-criteria coverage: "PDF uploaded through curl returns a job id and document id" — Tasks 5, 8; "job status polled to completion" — Tasks 4, 6, 8; "Markdown and chunks retrieved" — Tasks 3, 6, 8; "same file and configuration returns a cached result" — Task 8's re-upload check, resting on the existing content-addressed `document_id` and conversion cache.
- Deliverable coverage: FastAPI service with async job endpoints (5, 6); file upload (5); filesystem artifact storage (3); SQLite metadata and job table (2); versioned cache keys (already shipped in 0.1.0 — the key includes engine and DocSift versions); document retrieval and deletion (6); OpenAPI (7).
- NFR-04 mapping: unsupported content types → 415 (Task 5); upload size limit → 413, enforced while streaming so a huge body is never buffered (Task 5); filename sanitization and path traversal → only the suffix is used and `document_dir` validates ids against `doc_{12 hex}` (Tasks 3, 5); files processed outside the source directory → uploads go to `<data_dir>/uploads` (Task 5); non-root container (Task 8); untrusted-document risk documented (Task 8). Request/processing timeouts are configured but not enforced per-job — noted as a gap below.
- Known gap, deliberately left for the whole-branch review to triage: `job_timeout_seconds` is read into `Settings` but nothing enforces it, so a pathological document could occupy a worker indefinitely. Enforcing it needs process-level isolation to be meaningful (a thread cannot be safely killed mid-conversion), which is a bigger design decision than M4 should absorb. The startup reconciliation limits the blast radius to one process lifetime.
- Type consistency: `JobRecord` fields (Task 4) match the SQLite `jobs` columns (Task 2) and `JobStatusResponse` (Task 5/6); `documents.store_result`/`load_result`/`delete_document_files` (Task 3) are used with identical names in Tasks 4 and 6; `get_settings()` (Task 1) is consumed by Tasks 2, 3, 4 and 5; job statuses are the same four strings everywhere.
- Every task touching the service, engines or API carries the CI-parity check, and every new module gets added to the lazy-import guard in Task 7 — the two regression classes this project has actually shipped.
