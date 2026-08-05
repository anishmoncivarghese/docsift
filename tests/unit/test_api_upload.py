from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from docsift import __version__  # noqa: E402
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
        return EngineOutput(markdown="# Api\n\nBody text.\n", engine_version="9.9.9")


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

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def engine():
    register_engine("markitdown", OkEngine)
    yield
    unregister_engine("markitdown")


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version(client):
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": __version__}


def test_upload_is_accepted_and_returns_ids(client, engine):
    response = client.post(
        "/v1/documents", files={"file": ("note.txt", b"hello world", "text/plain")}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["job_id"].startswith("job_")
    assert body["document_id"].startswith("doc_")
    assert body["status"] == "queued"


def test_unsupported_extension_is_rejected(client, engine):
    response = client.post("/v1/documents", files={"file": ("movie.mp4", b"data", "video/mp4")})
    assert response.status_code == 415


def test_empty_upload_is_rejected(client, engine):
    response = client.post("/v1/documents", files={"file": ("note.txt", b"", "text/plain")})
    assert response.status_code == 400


def test_oversized_upload_is_rejected(client, engine, monkeypatch):
    monkeypatch.setenv("DOCSIFT_MAX_UPLOAD_BYTES", "10")
    response = client.post("/v1/documents", files={"file": ("note.txt", b"x" * 100, "text/plain")})
    assert response.status_code == 413


def test_client_filename_cannot_escape_the_data_directory(client, engine, tmp_path):
    response = client.post(
        "/v1/documents",
        files={"file": ("../../evil.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 202
    assert not (tmp_path / "evil.txt").exists()
    assert not Path("/tmp/evil.txt").exists()


def test_service_unavailable_while_shutting_down_returns_503(client, engine, monkeypatch):
    from docsift.core.exceptions import ServiceUnavailableError
    from docsift.services import job_service

    def _raise_unavailable(*args, **kwargs):
        raise ServiceUnavailableError("service is shutting down")

    monkeypatch.setattr(job_service, "submit", _raise_unavailable)
    response = client.post(
        "/v1/documents", files={"file": ("note.txt", b"hello world", "text/plain")}
    )
    assert response.status_code == 503


def test_importing_the_app_pulls_no_engine_modules():
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import docsift.api.app\n"
        "banned = {'docling', 'markitdown', 'torch', 'transformers'}\n"
        "loaded = {m.split('.')[0] for m in sys.modules}\n"
        "sys.exit(1 if banned & loaded else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
