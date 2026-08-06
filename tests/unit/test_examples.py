import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

EXAMPLES = Path(__file__).parent.parent.parent / "examples"


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
    routes = _routes()
    template_paths = {
        path.replace("{document_id}", "").replace("{job_id}", "") for _, path in routes
    }
    called = [
        node["parameters"]["url"]
        for node in workflow["nodes"]
        if node.get("type") == "n8n-nodes-base.httpRequest"
    ]
    assert called, "workflow must make HTTP calls"
    for url in called:
        tail = url.split("}}", 1)[-1]
        assert any(
            tail.startswith(prefix) or prefix.rstrip("/") in tail for prefix in template_paths
        ), f"workflow calls an endpoint that does not exist: {tail}"


def test_n8n_workflow_polls_before_searching():
    workflow = json.loads(
        (EXAMPLES / "n8n" / "docsift-convert-and-search.json").read_text(encoding="utf-8")
    )
    names = [node["name"] for node in workflow["nodes"]]
    assert any("poll" in name.lower() or "job" in name.lower() for name in names)
    assert any("search" in name.lower() for name in names)


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
