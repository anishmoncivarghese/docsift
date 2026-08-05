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


def test_init_db_migrates_a_database_created_before_cancel_requested_existed(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "legacy"))
    legacy_path = database.database_path()
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(legacy_path)
    try:
        connection.execute(
            "CREATE TABLE jobs ("
            " job_id TEXT PRIMARY KEY, document_id TEXT, status TEXT NOT NULL,"
            " error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.commit()
    finally:
        connection.close()

    database.init_db()
    database.create_job("job_legacy", "doc_legacy")
    assert database.request_cancel("doc_legacy") == 1
    assert database.is_cancel_requested("job_legacy") is True


def test_request_cancel_only_flags_unfinished_jobs():
    database.create_job("job_done", "doc_a")
    database.set_job_status("job_done", "succeeded", document_id="doc_a")
    assert database.request_cancel("doc_a") == 0
    assert database.is_cancel_requested("job_done") is False


def test_is_cancel_requested_is_false_for_unknown_job():
    assert database.is_cancel_requested("job_missing") is False


def test_set_job_status_truncates_long_error_text():
    database.create_job("job_long_error", None)
    database.set_job_status("job_long_error", "failed", error="x" * 10_000)
    assert len(database.get_job("job_long_error")["error"]) == 500
