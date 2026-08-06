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
        return EngineOutput(markdown="# Doc\n\nBody.\n", engine_version="9.9.9")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("DOCSIFT_API_KEY", raising=False)
    from docsift.services import job_service

    job_service.reset_for_tests()
    yield
    job_service.shutdown()
    job_service.reset_for_tests()


@pytest.fixture
def engine():
    register_engine("markitdown", OkEngine)
    yield
    unregister_engine("markitdown")


def _client():
    from docsift.api.app import create_app

    return TestClient(create_app())


def test_no_key_configured_means_no_authentication(engine):
    with _client() as client:
        response = client.post(
            "/v1/documents", files={"file": ("note.txt", b"hello", "text/plain")}
        )
    assert response.status_code == 202


def test_configured_key_is_required_on_v1_routes(engine, monkeypatch):
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        response = client.post(
            "/v1/documents", files={"file": ("note.txt", b"hello", "text/plain")}
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid or missing API key"


def test_correct_key_is_accepted(engine, monkeypatch):
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("note.txt", b"hello", "text/plain")},
            headers={"X-API-Key": "s3cret"},
        )
    assert response.status_code == 202


def test_wrong_key_is_rejected_without_echoing_it(engine, monkeypatch):
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("note.txt", b"hello", "text/plain")},
            headers={"X-API-Key": "wrong-guess-value"},
        )
    assert response.status_code == 401
    assert "wrong-guess-value" not in response.text


def test_health_and_version_stay_open(monkeypatch):
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        assert client.get("/health").status_code == 200
        assert client.get("/version").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_security_scheme_appears_only_when_a_key_is_configured(monkeypatch):
    with _client() as client:
        document = client.get("/openapi.json").json()
    assert "securitySchemes" not in document.get("components", {})

    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        document = client.get("/openapi.json").json()
    scheme = document["components"]["securitySchemes"]["ApiKeyHeader"]
    assert scheme == {"type": "apiKey", "in": "header", "name": "X-API-Key"}
