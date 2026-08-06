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


def test_missing_key_is_rejected_before_multipart_body_is_parsed(monkeypatch):
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        response = client.post(
            "/v1/documents",
            content=b"not valid multipart data",
            headers={"Content-Type": "multipart/form-data; boundary=missing"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid or missing API key"


def test_health_and_version_stay_open(monkeypatch):
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        assert client.get("/health").status_code == 200
        assert client.get("/version").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_api_key_is_enforced_under_a_root_path(monkeypatch):
    """uvicorn prepends root_path to scope['path']; the guard must not be fooled."""
    import anyio

    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    from docsift.api.app import create_app

    app = create_app()
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/jobs/job_abc",
        "raw_path": b"/api/v1/jobs/job_abc",
        "root_path": "/api",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "client": ("test", 1),
        "server": ("testserver", 80),
    }
    anyio.run(app, scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 401


def test_an_unknown_route_outside_v1_still_requires_the_key(monkeypatch):
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        assert client.get("/admin/whatever").status_code == 401


def test_a_duplicated_api_key_header_is_rejected_outright(engine, monkeypatch):
    """dict(scope["headers"]) keeps only the last duplicate -- reject instead of picking one."""
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("note.txt", b"hello", "text/plain")},
            headers=[("X-API-Key", "wrong"), ("X-API-Key", "s3cret")],
        )
    assert response.status_code == 401


def test_security_scheme_appears_only_when_a_key_is_configured(monkeypatch):
    with _client() as client:
        document = client.get("/openapi.json").json()
    assert "securitySchemes" not in document.get("components", {})

    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        document = client.get("/openapi.json").json()
    scheme = document["components"]["securitySchemes"]["ApiKeyHeader"]
    assert scheme == {"type": "apiKey", "in": "header", "name": "X-API-Key"}

    assert "security" not in document
    for path, path_item in document["paths"].items():
        for operation in path_item.values():
            if path.startswith("/v1/"):
                assert operation["security"] == [{"ApiKeyHeader": []}]
            else:
                assert "security" not in operation


def test_api_key_is_not_exposed_as_an_ordinary_operation_parameter(monkeypatch):
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    with _client() as client:
        document = client.get("/openapi.json").json()
    for path_item in document["paths"].values():
        for operation in path_item.values():
            names = {parameter["name"].lower() for parameter in operation.get("parameters", [])}
            assert "x-api-key" not in names
