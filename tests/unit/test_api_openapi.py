import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from docsift.api.app import create_app  # noqa: E402

EXPECTED_OPERATIONS = {
    "getHealth",
    "getVersion",
    "uploadDocument",
    "getJobStatus",
    "getDocument",
    "getDocumentMarkdown",
    "getDocumentChunks",
    "deleteDocument",
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))


def test_openapi_document_is_served():
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "DocSift"


def test_every_operation_has_a_stable_id():
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()
    found = {
        operation["operationId"]
        for path in document["paths"].values()
        for operation in path.values()
        if "operationId" in operation
    }
    assert EXPECTED_OPERATIONS <= found


def test_upload_is_documented_as_accepted_not_ok():
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()
    assert "202" in document["paths"]["/v1/documents"]["post"]["responses"]


def test_serve_command_exists():
    from typer.testing import CliRunner

    from docsift.cli.main import app

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output


def test_every_operation_has_an_agent_readable_summary_and_description():
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()
    operations = [
        operation
        for path in document["paths"].values()
        for operation in path.values()
        if "operationId" in operation
    ]
    assert len(operations) == 9
    for operation in operations:
        assert operation.get("summary"), operation["operationId"]
        description = operation.get("description", "")
        assert len(description) >= 40, (operation["operationId"], description)


def test_upload_description_tells_an_agent_to_poll():
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()
    description = document["paths"]["/v1/documents"]["post"]["description"].lower()
    assert "poll" in description
    assert "job" in description


def test_servers_entry_is_present_and_configurable(monkeypatch):
    monkeypatch.setenv("DOCSIFT_PUBLIC_URL", "https://docsift.example.com")
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()
    assert document["servers"][0]["url"] == "https://docsift.example.com"


def test_servers_entry_is_absent_when_no_public_url_is_configured(monkeypatch):
    # A 0.3.0 deployment that sets nothing must see no behavior change: a
    # servers entry defaulting to http://127.0.0.1:8000 would break "Try it
    # out" on a service actually reachable elsewhere, and would misdirect any
    # client regenerated from this document. to_swagger2 already falls back
    # to http://127.0.0.1:8000 for connector generation when servers is
    # absent, so this only affects the OpenAPI 3.1 document.
    monkeypatch.delenv("DOCSIFT_PUBLIC_URL", raising=False)
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()
    assert "servers" not in document
