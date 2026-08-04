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
