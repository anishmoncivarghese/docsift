import json
import re
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

EXAMPLES = Path(__file__).parent.parent.parent / "examples"
PROJECT_ROOT = EXAMPLES.parent

_N8N_EXPRESSION = re.compile(r"\{\{.*?\}\}")


def _normalize_template(path: str) -> str:
    """Collapse every `{name}` path parameter to a single placeholder."""
    return re.sub(r"\{[^}]+\}", "{param}", path)


def _normalize_called_url(url: str) -> str:
    """Reduce an n8n node's URL expression to a route-template-shaped path.

    Every `{{ ... }}` n8n expression -- the base URL and each dynamic path
    segment (job_id, document_id) -- collapses to one `{param}` placeholder,
    the same one route templates are normalized to. This must match the real
    template *exactly*, not as a substring: a call to
    `.../v1/documents/{{x}}/THIS-ROUTE-DOES-NOT-EXIST` or
    `.../v1/documentsXYZ` should fail, even though both contain
    `/v1/documents`.
    """
    normalized = _N8N_EXPRESSION.sub("{param}", url)
    return normalized[normalized.index("/v1/") :]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))


def _routes() -> set[tuple[str, str]]:
    from docsift.api.app import create_app

    document = create_app().openapi()
    return {
        (method.upper(), path)
        for path, operations in document["paths"].items()
        for method in operations
    }


def test_n8n_workflow_is_valid_json_and_importable():
    workflow = json.loads(
        (EXAMPLES / "n8n" / "docsift-convert-and-search.json").read_text(encoding="utf-8")
    )
    assert workflow["name"]
    assert isinstance(workflow["nodes"], list)
    assert len(workflow["nodes"]) >= 4
    assert "connections" in workflow


def test_n8n_workflow_calls_only_real_endpoints():
    workflow = json.loads(
        (EXAMPLES / "n8n" / "docsift-convert-and-search.json").read_text(encoding="utf-8")
    )
    normalized_routes = {(method, _normalize_template(path)) for method, path in _routes()}
    http_nodes = [
        node for node in workflow["nodes"] if node.get("type") == "n8n-nodes-base.httpRequest"
    ]
    assert http_nodes, "workflow must make HTTP calls"
    for node in http_nodes:
        method = node["parameters"].get("method", "GET").upper()
        url = node["parameters"]["url"]
        called = (method, _normalize_called_url(url))
        assert called in normalized_routes, (
            f"workflow calls an endpoint that does not exist: {method} {url}"
        )


def test_n8n_url_matching_rejects_a_route_with_an_extra_path_segment():
    normalized_routes = {(method, _normalize_template(path)) for method, path in _routes()}
    called = (
        "GET",
        _normalize_called_url(
            "={{ $json.baseUrl }}/v1/documents/{{ $json.id }}/THIS-ROUTE-DOES-NOT-EXIST"
        ),
    )
    assert called not in normalized_routes


def test_n8n_url_matching_rejects_a_similarly_prefixed_route():
    normalized_routes = {(method, _normalize_template(path)) for method, path in _routes()}
    called = ("GET", _normalize_called_url("={{ $json.baseUrl }}/v1/documentsXYZ"))
    assert called not in normalized_routes


def test_n8n_workflow_polls_before_searching():
    workflow = json.loads(
        (EXAMPLES / "n8n" / "docsift-convert-and-search.json").read_text(encoding="utf-8")
    )
    names = [node["name"] for node in workflow["nodes"]]
    assert any("poll" in name.lower() or "job" in name.lower() for name in names)
    assert any("search" in name.lower() for name in names)


def test_n8n_workflow_supplies_a_runnable_sample_document():
    workflow = json.loads(
        (EXAMPLES / "n8n" / "docsift-convert-and-search.json").read_text(encoding="utf-8")
    )
    nodes = {node["name"]: node for node in workflow["nodes"]}
    sample = nodes["Create sample document"]
    assert sample["type"] == "n8n-nodes-base.code"
    assert "binary" in sample["parameters"]["jsCode"]
    assert "data" in sample["parameters"]["jsCode"]
    assert workflow["connections"]["Settings"]["main"][0][0]["node"] == sample["name"]
    assert workflow["connections"][sample["name"]]["main"][0][0]["node"] == ("Upload document")


def test_n8n_workflow_stops_failed_jobs_and_limits_polling():
    workflow = json.loads(
        (EXAMPLES / "n8n" / "docsift-convert-and-search.json").read_text(encoding="utf-8")
    )
    nodes = {node["name"]: node for node in workflow["nodes"]}
    assert "Conversion failed?" in nodes
    assert nodes["Stop failed conversion"]["type"] == "n8n-nodes-base.stopAndError"
    assert "Polling limit reached?" in nodes
    assert nodes["Stop polling timeout"]["type"] == "n8n-nodes-base.stopAndError"

    settings = nodes["Settings"]["parameters"]["assignments"]["assignments"]
    assert any(item["name"] == "maxPolls" and item["value"] > 0 for item in settings)

    failed_outputs = workflow["connections"]["Conversion failed?"]["main"]
    assert failed_outputs[0][0]["node"] == "Stop failed conversion"
    assert failed_outputs[1][0]["node"] == "Polling limit reached?"
    limit_outputs = workflow["connections"]["Polling limit reached?"]["main"]
    assert limit_outputs[0][0]["node"] == "Stop polling timeout"
    assert limit_outputs[1][0]["node"] == "Wait before polling"


def test_connector_instructions_reference_real_operation_ids():
    from docsift.api.app import create_app

    document = create_app().openapi()
    operation_ids = {
        operation["operationId"]
        for path in document["paths"].values()
        for operation in path.values()
        if "operationId" in operation
    }
    text = (EXAMPLES / "copilot-studio" / "README.md").read_text(encoding="utf-8")
    mentioned = {name for name in operation_ids if name in text}
    assert {"uploadDocument", "getJobStatus", "searchDocument"} <= mentioned


def test_connector_instructions_use_the_swagger2_command():
    text = (EXAMPLES / "copilot-studio" / "README.md").read_text(encoding="utf-8")
    assert "docsift openapi" in text
    assert "swagger2" in text


def test_copilot_instructions_are_honest_about_polling():
    text = (EXAMPLES / "copilot-studio" / "README.md").read_text(encoding="utf-8").lower()
    assert "poll" in text
    assert "power automate" in text


def test_power_automate_example_uses_a_do_until_loop():
    text = (EXAMPLES / "power-automate" / "README.md").read_text(encoding="utf-8").lower()
    assert "do until" in text
    assert "getjobstatus" in text.replace(" ", "")


def test_examples_are_included_in_the_wheel():
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    force_include = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include["examples"] == "docsift/examples"
