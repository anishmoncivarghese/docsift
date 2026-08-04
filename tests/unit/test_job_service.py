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
