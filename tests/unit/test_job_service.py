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

    def convert(self, path: Path, options=None, on_progress=None) -> EngineOutput:
        return EngineOutput(markdown="# Job\n\nBody text.\n", engine_version="9.9.9")


class BoomEngine(OkEngine):
    def convert(self, path: Path, options=None, on_progress=None) -> EngineOutput:
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


def test_successful_job_indexes_its_chunks_for_search(upload):
    register_engine("markitdown", OkEngine)
    try:
        job_id, document_id = job_service.submit(upload, "upload.txt")
        assert _await_job(job_id) == "succeeded"
    finally:
        unregister_engine("markitdown")

    rows = database.search_document_chunks(document_id, "body", limit=5)
    assert [row["chunk_id"] for row in rows] == [f"{document_id}_c000"]


def test_reprocessing_same_document_replaces_its_search_rows(tmp_path):
    register_engine("markitdown", OkEngine)
    try:
        first = tmp_path / "first.txt"
        first.write_text("same bytes", encoding="utf-8")
        first_job, document_id = job_service.submit(first, "first.txt")
        assert _await_job(first_job) == "succeeded"

        second = tmp_path / "second.txt"
        second.write_text("same bytes", encoding="utf-8")
        second_job, second_document_id = job_service.submit(second, "second.txt")
        assert _await_job(second_job) == "succeeded"
    finally:
        unregister_engine("markitdown")

    assert second_document_id == document_id
    rows = database.search_document_chunks(document_id, "body", limit=5)
    assert [row["chunk_id"] for row in rows] == [f"{document_id}_c000"]


def test_failed_conversion_never_indexes_any_chunks(upload):
    """Task 2's required test list included this and no added test actually
    asserted it -- the code is correct today, but nothing pins it."""
    register_engine("markitdown", BoomEngine)
    try:
        job_id, document_id = job_service.submit(upload, "upload.txt")
        assert _await_job(job_id) == "failed"
    finally:
        unregister_engine("markitdown")

    assert database.search_document_chunks(document_id, "document", limit=5) == []


def test_job_cancelled_by_a_concurrent_delete_never_indexes_any_chunks(tmp_path):
    import threading

    release = threading.Event()

    class SlowEngine(OkEngine):
        def convert(self, path: Path, options=None, on_progress=None) -> EngineOutput:
            release.wait(timeout=30)
            return EngineOutput(markdown="# Job\n\nBody text.\n", engine_version="9.9.9")

    register_engine("markitdown", SlowEngine)
    try:
        source = tmp_path / "cancel_me.txt"
        source.write_text("hello world", encoding="utf-8")
        job_id, document_id = job_service.submit(source, "cancel_me.txt")

        deadline = time.time() + 10
        while time.time() < deadline:
            record = job_service.get(job_id)
            if record and record.status == "processing":
                break
            time.sleep(0.02)
        else:
            raise AssertionError("job never reached processing")
        assert database.request_cancel(document_id) == 1

        release.set()
        assert _await_job(job_id) == "failed"
    finally:
        unregister_engine("markitdown")

    assert database.search_document_chunks(document_id, "body", limit=5) == []


def test_index_failure_fails_job_without_exposing_document_content(upload, monkeypatch):
    def fail_index(*args, **kwargs):
        raise RuntimeError("secret document content")

    monkeypatch.setattr(database, "index_document_chunks", fail_index)
    register_engine("markitdown", OkEngine)
    try:
        job_id, document_id = job_service.submit(upload, "upload.txt")
        assert _await_job(job_id) == "failed"
    finally:
        unregister_engine("markitdown")

    record = job_service.get(job_id)
    assert record.error == "RuntimeError"
    assert database.get_document(document_id) is None


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


def test_failed_job_error_names_the_original_filename_not_the_temp_copy(tmp_path):
    """conversion_service only ever sees the server-side temp copy, so a
    ConversionFailedError it raises quotes the temp file's generated name
    (e.g. 'tmpwnsd410q.pdf'), not the name the client uploaded. _run must swap
    that back to the client's filename before the error is stored and served
    by GET /v1/jobs/{id} -- otherwise a user who uploaded 'q3-report.pdf' is
    told a file they never named failed, and the temp-naming scheme leaks."""

    class RaisingEngine(OkEngine):
        def convert(self, path: Path, options=None, on_progress=None) -> EngineOutput:
            raise RuntimeError("boom")

    source = tmp_path / "tmpxyz123.pdf"
    source.write_text("hello world", encoding="utf-8")

    register_engine("markitdown", RaisingEngine)
    try:
        job_id, _ = job_service.submit(source, "q3-report.pdf", engine="markitdown")
        assert _await_job(job_id) == "failed"
    finally:
        unregister_engine("markitdown")
    record = job_service.get(job_id)
    assert "tmpxyz123" not in (record.error or "")
    assert "q3-report.pdf" in (record.error or "")


def test_startup_sweeps_orphaned_uploads_left_by_a_crashed_process(tmp_path):
    """A process killed between writing a temp upload and _run's finally
    block (which normally unlinks it) leaves the original sitting in
    uploads/ forever -- nothing else ever revisits it. startup() runs before
    this process has accepted any work of its own, so anything already in
    uploads/ at that point cannot belong to a job this process is running."""
    from docsift.core.config import get_settings

    uploads = get_settings().data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    orphan = uploads / "tmpabc123.pdf"
    orphan.write_bytes(b"leftover from a crashed process")

    job_service.startup()

    assert not orphan.exists()


def test_unknown_job_is_none():
    assert job_service.get("job_missing") is None


def test_startup_fails_jobs_left_behind_by_a_dead_process():
    database.create_job("job_orphan", None)
    database.set_job_status("job_orphan", "processing")
    job_service.startup()
    record = job_service.get("job_orphan")
    assert record.status == "failed"
    assert record.error == "interrupted"


def test_submit_after_shutdown_raises_a_domain_error(upload):
    from docsift.core.exceptions import ServiceUnavailableError

    job_service.shutdown()
    with pytest.raises(ServiceUnavailableError):
        job_service.submit(upload, "upload.txt")


def test_concurrent_submit_and_shutdown_never_leaks_a_runtime_error(tmp_path):
    import threading

    from docsift.core.exceptions import ServiceUnavailableError

    register_engine("markitdown", OkEngine)
    errors: list[BaseException] = []

    def submitter() -> None:
        for index in range(20):
            source = tmp_path / f"racer-{threading.get_ident()}-{index}.txt"
            source.write_text("hello world", encoding="utf-8")
            try:
                job_service.submit(source, source.name)
            except ServiceUnavailableError:
                pass
            except BaseException as exc:  # noqa: BLE001 - the point of the test
                errors.append(exc)

    threads = [threading.Thread(target=submitter) for _ in range(6)]
    try:
        for thread in threads:
            thread.start()
        # Give the submitter threads a chance to actually get scheduled and
        # start racing before we shut down. Without this, `shutdown()` below
        # tends to run before any thread has been scheduled by the OS, finds
        # `_executor is None`, and no-ops -- masking the race instead of
        # exercising it.
        time.sleep(0.002)
        job_service.shutdown()
        for thread in threads:
            thread.join(timeout=30)
    finally:
        unregister_engine("markitdown")
    assert errors == [], [type(e).__name__ for e in errors]


def test_a_worker_that_crashes_in_bookkeeping_does_not_strand_the_job(upload, monkeypatch):
    from docsift.services import job_service as module

    def explode(*args, **kwargs):
        raise RuntimeError("bookkeeping is broken")

    register_engine("markitdown", OkEngine)
    monkeypatch.setattr(module, "_run", explode)
    try:
        job_id, _ = job_service.submit(upload, "upload.txt")
        assert _await_job(job_id) == "failed"
    finally:
        unregister_engine("markitdown")
    assert job_service.get(job_id).error == "RuntimeError"
