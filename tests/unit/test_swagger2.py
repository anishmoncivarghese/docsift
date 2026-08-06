import pytest

pytest.importorskip("fastapi")

from openapi_spec_validator import validate  # noqa: E402

from docsift.api.swagger2 import UnsupportedConstructError, to_swagger2  # noqa: E402


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("DOCSIFT_API_KEY", raising=False)


def _document(**env) -> dict:
    from docsift.api.app import create_app

    return create_app().openapi()


def test_emitted_document_is_valid_swagger_2():
    swagger = to_swagger2(_document())
    validate(swagger)  # raises if invalid
    assert swagger["swagger"] == "2.0"


def test_host_and_scheme_come_from_the_servers_entry(monkeypatch):
    monkeypatch.setenv("DOCSIFT_PUBLIC_URL", "https://docsift.example.com/api")
    swagger = to_swagger2(_document())
    assert swagger["host"] == "docsift.example.com"
    assert swagger["basePath"] == "/api"
    assert swagger["schemes"] == ["https"]


def test_every_operation_keeps_its_id_summary_and_description():
    swagger = to_swagger2(_document())
    operations = [operation for path in swagger["paths"].values() for operation in path.values()]
    assert len(operations) == 9
    for operation in operations:
        assert operation["operationId"]
        assert operation["summary"]
        assert operation["description"]


def test_upload_becomes_a_multipart_form_operation():
    swagger = to_swagger2(_document())
    upload = swagger["paths"]["/v1/documents"]["post"]
    assert "multipart/form-data" in upload["consumes"]
    parameters = {p["name"]: p for p in upload["parameters"]}
    assert parameters["file"]["in"] == "formData"
    assert parameters["file"]["type"] == "file"
    assert parameters["engine"]["in"] == "formData"


def test_search_query_parameters_are_preserved_with_their_bounds():
    swagger = to_swagger2(_document())
    search = swagger["paths"]["/v1/documents/{document_id}/search"]["get"]
    parameters = {p["name"]: p for p in search["parameters"]}
    assert parameters["q"]["in"] == "query"
    assert parameters["q"]["required"] is True
    assert parameters["limit"]["maximum"] == 20
    assert parameters["document_id"]["in"] == "path"


def test_schema_references_point_at_definitions():
    swagger = to_swagger2(_document())
    assert "definitions" in swagger
    assert "components" not in swagger
    serialized = str(swagger)
    assert "#/components/schemas/" not in serialized
    assert "#/definitions/" in serialized


def test_nullable_unions_are_flattened():
    swagger = to_swagger2(_document())
    job = swagger["definitions"]["JobStatusResponse"]["properties"]["document_id"]
    assert "anyOf" not in job
    assert job["type"] == "string"
    assert job["x-nullable"] is True


def test_api_key_scheme_is_converted(monkeypatch):
    monkeypatch.setenv("DOCSIFT_API_KEY", "s3cret")
    swagger = to_swagger2(_document())
    assert swagger["securityDefinitions"]["ApiKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    assert swagger["security"] == [{"ApiKeyHeader": []}]


def test_an_unhandled_construct_raises_rather_than_emitting_a_broken_file():
    document = _document()
    document["paths"]["/v1/documents"]["post"]["requestBody"]["content"]["application/xml"] = {
        "schema": {"type": "string"}
    }
    with pytest.raises(UnsupportedConstructError, match="application/xml"):
        to_swagger2(document)


def test_cli_writes_a_swagger2_file(tmp_path):
    import json

    from typer.testing import CliRunner

    from docsift.cli.main import app

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    target = tmp_path / "connector.json"
    result = runner.invoke(app, ["openapi", "--output", str(target)])
    assert result.exit_code == 0, result.output

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["swagger"] == "2.0"
    validate(document)


def test_cli_rejects_an_unknown_format():
    from typer.testing import CliRunner

    from docsift.cli.main import app

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["openapi", "--format", "yaml"])
    assert result.exit_code == 1
