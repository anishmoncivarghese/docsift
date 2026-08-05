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
    assert (
        client.get("/v1/documents/doc_000000000000/search", params={"q": "body"}).status_code == 404
    )


@pytest.mark.parametrize("bad_id", ["not-a-doc-id", "doc_ABCDEF123456", "doc_short"])
def test_malformed_document_id_is_404_not_500(client, bad_id):
    assert client.get(f"/v1/documents/{bad_id}").status_code == 404
    assert client.get(f"/v1/documents/{bad_id}/markdown").status_code == 404
    assert client.get(f"/v1/documents/{bad_id}/chunks").status_code == 404
    assert client.get(f"/v1/documents/{bad_id}/search", params={"q": "body"}).status_code == 404
    assert client.delete(f"/v1/documents/{bad_id}").status_code == 404


def test_document_search_returns_ranked_chunk_metadata(client):
    _, document_id = _upload_and_wait(client)

    response = client.get(f"/v1/documents/{document_id}/search", params={"q": "body"})

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == document_id
    assert body["query"] == "body"
    assert body["estimated_tokens"] > 0
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["chunk_id"].startswith(document_id)
    assert result["match"] is True
    assert result["context_for"] is None
    assert isinstance(result["section_path"], list)
    assert isinstance(result["pages"], list)
    assert isinstance(result["score"], float)


def test_document_search_supports_phrase_queries_and_no_matches(client):
    _, document_id = _upload_and_wait(client)

    phrase = client.get(
        f"/v1/documents/{document_id}/search",
        params={"q": '"body paragraph"'},
    )
    missing = client.get(
        f"/v1/documents/{document_id}/search",
        params={"q": "platypus"},
    )

    assert phrase.status_code == 200
    assert len(phrase.json()["results"]) == 1
    assert missing.status_code == 200
    assert missing.json()["results"] == []


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": '"unterminated'},
        {"q": "body", "limit": 0},
        {"q": "body", "limit": 21},
        {"q": "body", "max_tokens": 0},
        {"q": "body", "max_tokens": 20001},
        {"q": "body", "context": -1},
        {"q": "body", "context": 3},
    ],
)
def test_document_search_rejects_invalid_controls_and_queries(client, params):
    _, document_id = _upload_and_wait(client)

    response = client.get(f"/v1/documents/{document_id}/search", params=params)

    assert response.status_code == 422
    assert "unterminated" not in response.text


def test_document_search_rejects_an_overlong_query_quickly(client):
    _, document_id = _upload_and_wait(client)

    start = time.time()
    response = client.get(
        f"/v1/documents/{document_id}/search", params={"q": "x" * 2000}
    )
    elapsed = time.time() - start

    assert response.status_code == 422
    assert elapsed < 1.0


def test_search_endpoint_has_stable_openapi_contract(client):
    operation = client.get("/openapi.json").json()["paths"]["/v1/documents/{document_id}/search"][
        "get"
    ]

    assert operation["operationId"] == "searchDocument"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SearchResponse"
    }


def test_reuploading_the_same_file_returns_the_same_document(client):
    _, first = _upload_and_wait(client)
    _, second = _upload_and_wait(client)
    assert first == second


def test_failed_job_still_carries_document_id(client):
    """document_id is the content address of the upload, assigned at submission
    before conversion runs -- it must be present on the job even when the
    conversion itself fails. Clients must check status == "succeeded" before
    treating document_id as usable."""

    class FailingEngine(ConversionEngine):
        name = "markitdown"

        @classmethod
        def is_available(cls) -> bool:
            return True

        @classmethod
        def version(cls) -> str:
            return "9.9.9"

        def convert(self, path: Path, options=None) -> EngineOutput:
            raise RuntimeError("boom")

    register_engine("markitdown", FailingEngine)
    try:
        response = client.post(
            "/v1/documents", files={"file": ("note.txt", b"hello world", "text/plain")}
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        document_id = response.json()["document_id"]

        deadline = time.time() + 15.0
        body = None
        while time.time() < deadline:
            body = client.get(f"/v1/jobs/{job_id}").json()
            if body["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.05)
        assert body is not None and body["status"] == "failed"
        assert body["document_id"] == document_id
    finally:
        register_engine("markitdown", OkEngine)


def test_delete_also_purges_the_cached_copy(client):
    from docsift.storage.cache import cache_entries, load_cached

    _, document_id = _upload_and_wait(client)
    assert any(
        (result := load_cached(entry.stem)) is not None and result.document_id == document_id
        for entry in cache_entries()
    )
    assert client.delete(f"/v1/documents/{document_id}").status_code == 204
    assert not any(
        (result := load_cached(entry.stem)) is not None and result.document_id == document_id
        for entry in cache_entries()
    )


def test_reuploading_after_delete_reconverts_rather_than_resurrecting(client):
    _, document_id = _upload_and_wait(client)
    assert client.delete(f"/v1/documents/{document_id}").status_code == 204
    _, second = _upload_and_wait(client)
    assert second == document_id
    assert client.get(f"/v1/documents/{document_id}").status_code == 200


def test_delete_during_conversion_is_not_undone(tmp_path, monkeypatch):
    import threading

    from docsift.api.app import create_app
    from docsift.core.config import get_settings
    from docsift.storage import cache

    release = threading.Event()

    class SlowEngine(ConversionEngine):
        name = "markitdown"

        @classmethod
        def is_available(cls) -> bool:
            return True

        @classmethod
        def version(cls) -> str:
            return "9.9.9"

        def convert(self, path, options=None) -> EngineOutput:
            release.wait(timeout=30)
            return EngineOutput(
                markdown="# Secret\n\nCONFIDENTIAL-XYZ body text.\n",
                engine_version="9.9.9",
            )

    register_engine("markitdown", SlowEngine)
    try:
        with TestClient(create_app()) as client:
            response = client.post(
                "/v1/documents",
                files={"file": ("note.txt", b"race me", "text/plain")},
            )
            job_id = response.json()["job_id"]
            document_id = response.json()["document_id"]
            deadline = time.time() + 10
            while time.time() < deadline:
                if client.get(f"/v1/jobs/{job_id}").json()["status"] == "processing":
                    break
                time.sleep(0.02)
            assert client.delete(f"/v1/documents/{document_id}").status_code in (202, 204)
            release.set()
            deadline = time.time() + 20
            while time.time() < deadline:
                if client.get(f"/v1/jobs/{job_id}").json()["status"] in (
                    "succeeded",
                    "failed",
                ):
                    break
                time.sleep(0.05)
            assert client.get(f"/v1/documents/{document_id}").status_code == 404
    finally:
        unregister_engine("markitdown")
    leaked = [
        path
        for base in (get_settings().data_dir, cache.cache_dir(create=False))
        for path in base.rglob("*")
        if path.is_file() and "CONFIDENTIAL-XYZ" in path.read_text(errors="ignore")
    ]
    assert leaked == [], leaked


def test_delete_failure_returns_json_500_not_a_bare_error(client, monkeypatch):
    from docsift.storage import documents

    _, document_id = _upload_and_wait(client)

    def _raise(directory):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(documents.shutil, "rmtree", _raise)
    response = client.delete(f"/v1/documents/{document_id}")
    assert response.status_code == 500
    assert response.json()["detail"] == "failed to delete document"


def test_delete_reports_500_when_a_cache_purge_fails(client, monkeypatch):
    """A cache entry that can't be unlinked must not be swallowed into a
    204 -- that would claim deletion succeeded while a readable copy of the
    document could still sit in the cache."""
    from docsift.storage import cache

    _, document_id = _upload_and_wait(client)

    monkeypatch.setattr(cache, "delete_entries_for_document", lambda doc_id: (0, 1))
    response = client.delete(f"/v1/documents/{document_id}")
    assert response.status_code == 500
    assert response.json()["detail"] == "failed to purge cached copies"
