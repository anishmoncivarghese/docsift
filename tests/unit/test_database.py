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
