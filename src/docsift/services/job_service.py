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
from docsift.storage import cache, database, documents

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_shutting_down = False
_pending_jobs = 0  # queued + processing; guarded by _executor_lock


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
    global _executor, _shutting_down, _pending_jobs
    with _executor_lock:
        executor = _executor
        _executor = None
        _shutting_down = False
        _pending_jobs = 0
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
    # in-flight jobs drain. cancel_futures=True drops anything still queued
    # (not yet started) instead of running it first, so a container's stop
    # grace period isn't spent draining an unbounded backlog before SIGKILL
    # turns it into orphaned uploads anyway.
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)


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
        if database.is_cancel_requested(job_id):
            # The client deleted this document while it was converting. Storing
            # now would resurrect it, so drop the cache entry convert_document
            # just wrote and record the job as cancelled.
            _removed, cache_failed = cache.delete_entries_for_document(result.document_id)
            error = "cancelled by delete"
            if cache_failed:
                # The cache entry convert_document just wrote could not be
                # purged -- content-safe to say so, since this names no
                # document content.
                error += " (cache purge failed)"
            database.set_job_status(job_id, "failed", error=error)
            return
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
        # DocSift's own errors are content-safe by construction, but
        # ConversionFailedError quotes path.name of whatever convert_document
        # was given -- the server-generated temp filename, since
        # conversion_service never sees the client's original name. Swap it
        # for the name the client actually used before it's stored and served
        # back by GET /v1/jobs/{id}; a straight substring replace is enough
        # since we know the exact temp name and don't need to parse the
        # message.
        message = str(exc).replace(source_path.name, filename)
        database.set_job_status(job_id, "failed", error=message)
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
        global _pending_jobs
        with _executor_lock:
            _pending_jobs -= 1
        if future.cancelled():
            # shutdown()'s cancel_futures=True cancelled this before it ever
            # ran; the job row stays "queued" and fail_stale_jobs() will
            # reconcile it as "interrupted" on the next startup, same as any
            # other job abandoned by a stopped process.
            return
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
    global _pending_jobs
    with _executor_lock:
        if _shutting_down:
            raise ServiceUnavailableError("service is shutting down")
        if _pending_jobs >= get_settings().max_pending_jobs:
            # Each queued job pins its uploaded original on disk until a
            # worker picks it up, so an unbounded backlog is unbounded disk
            # use too. Reject rather than accept work no worker may reach for
            # a long time.
            raise ServiceUnavailableError("job backlog is full; try again later")
        _pending_jobs += 1
        database.create_job(job_id, document_id)
        future = _pool().submit(_run, job_id, source_path, filename, engine, options)
    future.add_done_callback(_worker_finished(job_id))
    return job_id, document_id


def get(job_id: str) -> JobRecord | None:
    row = database.get_job(job_id)
    return JobRecord(**row) if row else None
