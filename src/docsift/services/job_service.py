import contextlib
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from docsift.core.config import get_settings
from docsift.core.exceptions import DocSiftError, ServiceUnavailableError
from docsift.core.models import JobRecord
from docsift.core.options import ConversionOptions
from docsift.storage import database, documents

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_shutting_down = False


def _pool() -> ThreadPoolExecutor:
    """Build (or reuse) the executor. Callers must already hold `_executor_lock`."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=get_settings().job_workers, thread_name_prefix="docsift-job"
        )
    return _executor


def reset_for_tests() -> None:
    """Drop the executor so the next submit builds one from current settings."""
    global _executor, _shutting_down
    with _executor_lock:
        executor = _executor
        _executor = None
        _shutting_down = False
    if executor is not None:
        executor.shutdown(wait=True)


def startup() -> None:
    """Prepare the store and reconcile jobs abandoned by a previous process."""
    database.init_db()
    database.fail_stale_jobs()


def shutdown() -> None:
    global _executor, _shutting_down
    with _executor_lock:
        _shutting_down = True
        executor = _executor
        _executor = None
    # Wait for in-flight work outside the lock -- holding it here would block
    # every other caller of submit()/shutdown()/reset_for_tests() until the
    # in-flight jobs drain.
    if executor is not None:
        executor.shutdown(wait=True)


def _document_id_for(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"doc_{digest.hexdigest()[:12]}"


def _run(
    job_id: str, source_path: Path, filename: str, engine: str, options: ConversionOptions
) -> None:
    from docsift.services.conversion_service import convert_document

    database.set_job_status(job_id, "processing")
    try:
        result = convert_document(source_path, engine=engine, options=options)
        # convert_document derives source.filename from source_path.name -- the
        # temp file's name, since it never sees the client's original filename.
        # Restore the caller-supplied name here; it's metadata only (artifacts
        # are stored and looked up by document_id, never by this string), so
        # there's no path risk in using it as-is.
        result = result.model_copy(deep=True)
        result.source.filename = filename
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


def _worker_finished(job_id: str):
    """Catch a worker that died in its own error handling.

    `_run` records its own failures; reaching here means the bookkeeping itself
    raised, which would otherwise leave the job stuck in `processing`.
    """

    def callback(future) -> None:
        exc = future.exception()
        if exc is None:
            return
        with contextlib.suppress(Exception):
            database.set_job_status(job_id, "failed", error=type(exc).__name__)

    return callback


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
    with _executor_lock:
        if _shutting_down:
            raise ServiceUnavailableError("service is shutting down")
        database.create_job(job_id, document_id)
        future = _pool().submit(_run, job_id, source_path, filename, engine, options)
    future.add_done_callback(_worker_finished(job_id))
    return job_id, document_id


def get(job_id: str) -> JobRecord | None:
    row = database.get_job(job_id)
    return JobRecord(**row) if row else None
