# DocSift M6: Workflow Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DocSift usable from Copilot Studio, Power Automate and n8n — a Swagger 2.0 document that actually imports into a Power Platform custom connector, an optional API key so the deployed service is not open to anyone who finds the URL, agent-readable operation descriptions, and working example workflows.

**Architecture:** Three code changes and three artifacts. Code: agent-facing OpenAPI metadata on every route (FR-15); an optional single shared-secret API key, off by default, declared as a security scheme so connectors prompt for it; and a `docsift openapi` command that emits **Swagger 2.0**, because Power Platform custom connectors do not accept the OpenAPI 3.1 document FastAPI generates. Artifacts: an importable n8n workflow, Copilot Studio connector instructions, and a Power Automate flow description — all under `examples/`.

**Tech Stack:** No new runtime dependencies. `openapi-spec-validator` is added to the dev group only, to prove the emitted Swagger 2.0 is valid rather than merely plausible.

## Why this milestone has real code in it

Two facts discovered while planning, both of which change what "integration examples" means here:

1. **FastAPI emits OpenAPI 3.1.0. Power Platform custom connectors require Swagger 2.0.** Pasting `/openapi.json` into the connector wizard fails. Without a converter there is no connector, so the PRD's exit criterion "the OpenAPI file imports successfully into a Power Platform custom connector" cannot be met by documentation alone.
2. **The API has no authentication, and M6 is the milestone that puts its URL into other people's tools.** A connector pointing at an unauthenticated endpoint means anyone who learns the host can upload, read and delete documents. A single shared-secret header is not the "enterprise authentication" the PRD lists as a non-goal — it is the minimum that makes the connector deliverable safe to hand to a colleague.

## Global Constraints

- Everything from prior plans still binds: uv only; **lazy engine imports** (`docsift --help` works with no engines; the unit lane must not import docling); no engine types outside `engines/`; **document content never in logs, errors, job records or artifacts**; conventional commits; integration tests marked and excluded by default.
- **CI parity is mandatory.** CI installs `--extra markitdown --extra api`. After any task touching the service, engines or API, run this and paste the result in the report:
  ```bash
  uv venv /tmp/ci-parity --python 3.12
  VIRTUAL_ENV=/tmp/ci-parity uv pip install -e '.[markitdown,api]' pytest fpdf2 httpx
  VIRTUAL_ENV=/tmp/ci-parity uv run --no-project pytest tests/unit -q
  ```
- **No test may touch the real `~/.cache/docsift` or `~/.local/share/docsift`.** Every test that converts or starts the API sets BOTH `DOCSIFT_CACHE_DIR` and `DOCSIFT_DATA_DIR` to a tmp_path.
- **The API key is off by default.** A 0.3.0 user who upgrades and sets nothing must see no behaviour change. This is a hard backward-compatibility requirement, not a preference.
- All 288 existing tests must keep passing. If an existing assertion would need weakening, STOP and report BLOCKED. Changing a test *fixture* to express the same intent is allowed and must be explained.
- **A test that passes against the unfixed code protects nothing.** For every new test, verify it genuinely fails before the implementation and report the RED evidence.
- Do NOT modify plan files. Do not push; the controller pushes. Stage only files you changed — never `git add -A`.
- Repo root: `/Users/anish/DocBridge/docsift`. HEAD at plan time: `1a46f56`. Released: 0.3.0 on PyPI.

## Deliberately out of scope

- OAuth, Entra ID, per-user identity, multi-tenancy. One shared secret only.
- Publishing a certified connector to Microsoft's public connector gallery.
- Hosting DocSift anywhere. The examples assume a reachable base URL and say so.
- Changing the async job contract. Connectors poll, exactly as clients do today.

---

### Task 1: Agent-facing OpenAPI metadata

**Files:**
- Modify: `src/docsift/api/app.py`
- Test: `tests/unit/test_api_openapi.py`

**Interfaces:**
- Consumes: the existing routes and their `operation_id` values (`getHealth`, `getVersion`, `uploadDocument`, `getJobStatus`, `getDocument`, `getDocumentMarkdown`, `getDocumentChunks`, `deleteDocument`, `searchDocument`).
- Produces: every operation carries a `summary` written as an imperative action name and a `description` that tells an agent *when to call it and what to do next*. `create_app()` also sets `description` on the `FastAPI(...)` constructor and a `servers` entry driven by a new `DOCSIFT_PUBLIC_URL` environment variable (default `http://127.0.0.1:8000`), because a connector needs a host and Swagger 2.0 requires one.

FR-15 says operation names and descriptions must be "optimized for agent tool use". Today seven of nine operations have FastAPI's auto-generated title-case summary (`Get Job`, `Upload Document`) and no description at all. An agent choosing between tools sees only those strings.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_api_openapi.py`:

```python
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


def test_servers_entry_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("DOCSIFT_PUBLIC_URL", raising=False)
    with TestClient(create_app()) as client:
        document = client.get("/openapi.json").json()
    assert document["servers"][0]["url"] == "http://127.0.0.1:8000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_api_openapi.py -v`
Expected: the summary/description test FAILS (auto-generated summaries, empty descriptions) and both `servers` tests FAIL (`KeyError: 'servers'`).

- [ ] **Step 3: Implement**

In `src/docsift/api/app.py`, add the public-URL helper near the other module-level helpers:

```python
def _public_url() -> str:
    """Base URL advertised in the OpenAPI document.

    A custom connector needs a host, and Swagger 2.0 requires one, so the
    document cannot rely on the request's own origin the way a browser client can.
    """
    return os.environ.get("DOCSIFT_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
```

(add `import os` at module top if absent).

In `create_app()`, extend the `FastAPI(...)` construction with a description and servers:

```python
    app = FastAPI(
        title="DocSift",
        version=__version__,
        summary="Convert documents once. Give agents only what they need.",
        description=(
            "Convert PDFs and Office documents into clean Markdown and "
            "token-budgeted chunks, then search them. Conversion is "
            "asynchronous: upload returns a job id immediately and the caller "
            "polls until the job succeeds."
        ),
        servers=[{"url": _public_url(), "description": "DocSift service"}],
        lifespan=lifespan,
    )
```

Then give every route decorator a `summary` and `description`. Use exactly these:

| operation | summary | description |
|---|---|---|
| `getHealth` | `Check service health` | `Return ok when the service is running. Use this to verify connectivity before uploading a document.` |
| `getVersion` | `Get service version` | `Return the running DocSift version. Useful for confirming which release a deployment is on.` |
| `uploadDocument` | `Upload a document for conversion` | `Accept a PDF or Office document and start converting it in the background. Returns immediately with a job id and a document id. Conversion can take minutes, so poll the job with getJobStatus until its status is succeeded, then retrieve the result. Do not assume the document is ready when this returns.` |
| `getJobStatus` | `Check conversion progress` | `Return the status of a conversion job: queued, processing, succeeded or failed. Poll this after uploadDocument until the status is succeeded or failed. The document id is present even when the job fails, so always check the status before retrieving the document.` |
| `getDocument` | `Get the full conversion result` | `Return the complete conversion result for a document, including its Markdown, every chunk, and conversion metrics. Prefer searchDocument when you only need the parts relevant to a question, because this returns the whole document.` |
| `getDocumentMarkdown` | `Get the document as Markdown` | `Return the cleaned Markdown for a converted document as plain text. This is the whole document; prefer searchDocument when you only need relevant sections.` |
| `getDocumentChunks` | `Get all document chunks` | `Return every chunk of a converted document with its section path, page numbers and token count. This is the whole document; prefer searchDocument when you only need relevant sections.` |
| `deleteDocument` | `Delete a document` | `Permanently remove a document, its stored files, its search index and any cached copies. Cancels conversion if it is still running. This cannot be undone.` |
| `searchDocument` | `Search within a document` | `Return the chunks of one document most relevant to a keyword or quoted-phrase query, ranked and capped by a token budget. Use this instead of retrieving the whole document when answering a question about it. Supports quoted phrases and optional adjacent-chunk context.` |

Keep the existing `searchDocument` description if it already says something equivalent — but ensure it mentions preferring search over whole-document retrieval, since that is the behaviour this whole product exists to encourage.

- [ ] **Step 4: Run the full gate and CI parity**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`, then the docling-free run from Global Constraints.
Expected: 292 passed (288 + 4 new), 7 deselected, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/api/app.py tests/unit/test_api_openapi.py
git commit -m "feat: describe every API operation for agent tool use"
```

---

### Task 2: Optional API key

**Files:**
- Modify: `src/docsift/core/config.py`, `src/docsift/api/app.py`
- Test: `tests/unit/test_api_auth.py`

**Interfaces:**
- Consumes: `get_settings()`.
- Produces:
  - `Settings.api_key: str | None = None`, read from `DOCSIFT_API_KEY` at call time. Empty or unset means disabled.
  - An ASGI dependency enforcing the header `X-API-Key` on every `/v1/*` route when a key is configured. `/health`, `/version`, `/openapi.json` and the docs routes stay open — the container `HEALTHCHECK` and connector import both need them.
  - `401` with `{"detail": "invalid or missing API key"}` when a key is configured and the header is absent or wrong. **The submitted value is never echoed.**
  - Comparison uses `secrets.compare_digest`, so a wrong key cannot be discovered by timing.
  - An `apiKey` security scheme named `ApiKeyHeader` in the OpenAPI document whenever a key is configured, so the connector wizard prompts for it.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_api_auth.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_api_auth.py -v`
Expected: the four key-enforcement tests FAIL (uploads succeed without a key) and the security-scheme test FAILS (`KeyError`). The two "open by default" tests pass — they pin the backward-compatibility guarantee, so note in your report that they are guards rather than RED evidence.

- [ ] **Step 3: Implement**

In `src/docsift/core/config.py`, add to `Settings`:

```python
    api_key: str | None = None
```

and in `get_settings()`:

```python
        api_key=os.environ.get("DOCSIFT_API_KEY") or None,
```

In `src/docsift/api/app.py`, add the dependency and wire it to the `/v1` routes:

```python
import secrets

from fastapi import Header


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce the shared secret when one is configured.

    Off unless `DOCSIFT_API_KEY` is set, so an existing deployment keeps working
    unchanged. `compare_digest` keeps a wrong key from being discovered by timing.
    The submitted value is never echoed back.
    """
    configured = get_settings().api_key
    if configured is None:
        return
    if x_api_key is None or not secrets.compare_digest(x_api_key, configured):
        raise HTTPException(status_code=401, detail="invalid or missing API key")
```

Apply it to every `/v1/*` route by adding `dependencies=[Depends(_require_api_key)]` to each route decorator (import `Depends` from fastapi). Do **not** apply it to `/health` or `/version`.

Then declare the scheme so connectors prompt for it. After the routes are registered in `create_app()`:

```python
    if get_settings().api_key is not None:
        def custom_openapi() -> dict:
            if app.openapi_schema:
                return app.openapi_schema
            schema = get_openapi(
                title=app.title,
                version=app.version,
                summary=app.summary,
                description=app.description,
                routes=app.routes,
                servers=app.servers,
            )
            schema.setdefault("components", {})["securitySchemes"] = {
                "ApiKeyHeader": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
            }
            schema["security"] = [{"ApiKeyHeader": []}]
            app.openapi_schema = schema
            return schema

        app.openapi = custom_openapi
```

(import `from fastapi.openapi.utils import get_openapi`). Note the schema is cached on the app instance and `create_app()` is called per test, so a settings change between tests is picked up correctly.

- [ ] **Step 4: Run the full gate and CI parity**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`, then the docling-free run.
Expected: 299 passed, 7 deselected, ruff clean. Confirm explicitly that the pre-existing API tests — which send no key — still pass, proving the default-off guarantee.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/core/config.py src/docsift/api/app.py tests/unit/test_api_auth.py
git commit -m "feat: add an optional shared-secret API key, off by default"
```

---

### Task 3: Swagger 2.0 export

**Files:**
- Create: `src/docsift/api/swagger2.py`
- Modify: `src/docsift/cli/main.py`, `pyproject.toml` (dev group)
- Test: `tests/unit/test_swagger2.py`

**Interfaces:**
- Consumes: the OpenAPI 3.1 dictionary produced by `create_app().openapi()`.
- Produces:
  - `api.swagger2.to_swagger2(openapi: dict) -> dict` — converts the subset of OpenAPI 3.1 this API actually uses into a valid Swagger 2.0 document.
  - `api.swagger2.UnsupportedConstructError(DocSiftError)` — raised when the input uses a construct the converter does not handle, so a future route cannot silently produce a broken connector file.
  - CLI `docsift openapi [--format openapi3|swagger2] [--output PATH]`, printing to stdout when `--output` is omitted. The service import stays inside the command function.
- `openapi-spec-validator>=0.7` is added to `[dependency-groups] dev` — the test validates the emitted document rather than asserting on a handful of keys.

**Why this exists:** Power Platform custom connectors take Swagger 2.0. FastAPI emits OpenAPI 3.1.0. Without this, the PRD's exit criterion "the OpenAPI file imports successfully into a Power Platform custom connector" is unreachable.

Conversions required for this API specifically:
- `openapi: "3.1.0"` → `swagger: "2.0"`.
- `servers[0].url` → `host` + `basePath` + `schemes`.
- `components.schemas` → `definitions`; every `#/components/schemas/X` reference → `#/definitions/X`.
- `components.securitySchemes` → `securityDefinitions`.
- `requestBody` with `multipart/form-data` → `consumes: [multipart/form-data]` plus `in: formData` parameters, with the file part typed `type: file`.
- `requestBody` with `application/json` → a single `in: body` parameter.
- Response `content.<media>.schema` → `schema`, plus `produces`.
- **`anyOf: [{type: X}, {type: "null"}]` → `type: X` with `x-nullable: true`.** Pydantic emits this for every `str | None` field and Swagger 2.0 has no `anyOf`; leaving it produces a document the connector wizard rejects.
- `examples` (3.1 plural) dropped; `const` dropped.

- [ ] **Step 1: Add the dev dependency**

In `pyproject.toml` `[dependency-groups] dev`, add `"openapi-spec-validator>=0.7"`. Run `uv sync --all-extras` and confirm `uv run python -c "import openapi_spec_validator; print('ok')"` prints `ok`.

- [ ] **Step 2: Write the failing test**

`tests/unit/test_swagger2.py`:

```python
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
    operations = [
        operation
        for path in swagger["paths"].values()
        for operation in path.values()
    ]
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
    document["paths"]["/v1/documents"]["post"]["requestBody"]["content"][
        "application/xml"
    ] = {"schema": {"type": "string"}}
    with pytest.raises(UnsupportedConstructError, match="application/xml"):
        to_swagger2(document)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_swagger2.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.api.swagger2`.

- [ ] **Step 4: Implement the converter**

`src/docsift/api/swagger2.py`:

```python
"""Convert this API's OpenAPI 3.1 document into Swagger 2.0.

Power Platform custom connectors accept Swagger 2.0; FastAPI emits OpenAPI 3.1,
so the generated document cannot be imported directly. This converter handles
the constructs this API actually uses and raises on anything else, so a route
added later cannot silently produce a connector file that fails to import.
"""

from typing import Any
from urllib.parse import urlparse

from docsift.core.exceptions import DocSiftError

_SUPPORTED_REQUEST_MEDIA = {"multipart/form-data", "application/json"}


class UnsupportedConstructError(DocSiftError):
    """The OpenAPI document uses something this converter does not handle."""


def _convert_refs(node: Any) -> Any:
    if isinstance(node, dict):
        converted = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                converted[key] = value.replace("#/components/schemas/", "#/definitions/")
            else:
                converted[key] = _convert_refs(value)
        return converted
    if isinstance(node, list):
        return [_convert_refs(item) for item in node]
    return node


def _flatten_nullable(node: Any) -> Any:
    """Rewrite `anyOf: [X, null]` as X with `x-nullable`.

    Pydantic emits that shape for every optional field; Swagger 2.0 has no
    `anyOf`, and a connector wizard rejects a document containing one.
    """
    if isinstance(node, list):
        return [_flatten_nullable(item) for item in node]
    if not isinstance(node, dict):
        return node

    node = {key: _flatten_nullable(value) for key, value in node.items()}
    options = node.get("anyOf")
    if isinstance(options, list):
        non_null = [o for o in options if o.get("type") != "null"]
        has_null = len(non_null) != len(options)
        if len(non_null) == 1:
            merged = dict(non_null[0])
            for key, value in node.items():
                if key != "anyOf":
                    merged.setdefault(key, value)
            if has_null:
                merged["x-nullable"] = True
            return merged
    node.pop("examples", None)
    node.pop("const", None)
    return node


def _split_server(url: str) -> tuple[str, str, list[str]]:
    parsed = urlparse(url)
    if not parsed.netloc:
        raise UnsupportedConstructError(f"server url is not absolute: {url}")
    base_path = parsed.path.rstrip("/") or "/"
    return parsed.netloc, base_path, [parsed.scheme or "http"]


def _request_body_parameters(operation: dict) -> tuple[list[dict], list[str]]:
    body = operation.get("requestBody")
    if body is None:
        return [], []
    content = body.get("content", {})
    unsupported = set(content) - _SUPPORTED_REQUEST_MEDIA
    if unsupported:
        raise UnsupportedConstructError(
            f"unsupported request media type(s): {sorted(unsupported)}"
        )
    required = bool(body.get("required"))

    if "multipart/form-data" in content:
        schema = _flatten_nullable(content["multipart/form-data"].get("schema", {}))
        properties = schema.get("properties", {})
        required_names = set(schema.get("required", []))
        parameters = []
        for name, spec in properties.items():
            parameter = {
                "name": name,
                "in": "formData",
                "required": name in required_names,
            }
            if spec.get("format") == "binary":
                parameter["type"] = "file"
            else:
                parameter["type"] = spec.get("type", "string")
                if "default" in spec:
                    parameter["default"] = spec["default"]
            if spec.get("description"):
                parameter["description"] = spec["description"]
            parameters.append(parameter)
        return parameters, ["multipart/form-data"]

    schema = _convert_refs(_flatten_nullable(content["application/json"]["schema"]))
    return [
        {"name": "body", "in": "body", "required": required, "schema": schema}
    ], ["application/json"]


def _convert_responses(operation: dict) -> tuple[dict, list[str]]:
    responses: dict[str, Any] = {}
    produces: list[str] = []
    for status, response in operation.get("responses", {}).items():
        converted: dict[str, Any] = {"description": response.get("description", "")}
        content = response.get("content", {})
        for media, media_object in content.items():
            if media not in produces:
                produces.append(media)
            if "schema" in media_object:
                converted["schema"] = _convert_refs(
                    _flatten_nullable(media_object["schema"])
                )
            break
        responses[str(status)] = converted
    return responses, produces


def to_swagger2(openapi: dict) -> dict:
    """Convert an OpenAPI 3.x document produced by this app into Swagger 2.0."""
    servers = openapi.get("servers") or [{"url": "http://127.0.0.1:8000"}]
    host, base_path, schemes = _split_server(servers[0]["url"])

    swagger: dict[str, Any] = {
        "swagger": "2.0",
        "info": {
            "title": openapi["info"]["title"],
            "version": openapi["info"]["version"],
            "description": openapi["info"].get("description")
            or openapi["info"].get("summary", ""),
        },
        "host": host,
        "basePath": base_path,
        "schemes": schemes,
        "paths": {},
    }

    for path, operations in openapi.get("paths", {}).items():
        converted_path: dict[str, Any] = {}
        for method, operation in operations.items():
            parameters = [
                _flatten_nullable(_convert_refs(parameter))
                for parameter in operation.get("parameters", [])
            ]
            for parameter in parameters:
                schema = parameter.pop("schema", None)
                if isinstance(schema, dict):
                    for key in (
                        "type",
                        "format",
                        "default",
                        "maximum",
                        "minimum",
                        "maxLength",
                        "minLength",
                        "enum",
                    ):
                        if key in schema:
                            parameter[key] = schema[key]
                    parameter.setdefault("type", "string")
            body_parameters, consumes = _request_body_parameters(operation)
            parameters.extend(body_parameters)
            responses, produces = _convert_responses(operation)

            converted: dict[str, Any] = {
                "operationId": operation["operationId"],
                "summary": operation.get("summary", ""),
                "description": operation.get("description", ""),
                "responses": responses,
            }
            if parameters:
                converted["parameters"] = parameters
            if consumes:
                converted["consumes"] = consumes
            if produces:
                converted["produces"] = produces
            converted_path[method] = converted
        swagger["paths"][path] = converted_path

    schemas = openapi.get("components", {}).get("schemas")
    if schemas:
        swagger["definitions"] = _convert_refs(_flatten_nullable(schemas))

    schemes_in = openapi.get("components", {}).get("securitySchemes")
    if schemes_in:
        swagger["securityDefinitions"] = schemes_in
    if openapi.get("security"):
        swagger["security"] = openapi["security"]

    return swagger
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_swagger2.py -v`
Expected: 9 passed. If `validate()` rejects the document, fix the converter — the validator is the contract, not the test's other assertions.

- [ ] **Step 6: Add the CLI command**

In `src/docsift/cli/main.py`, after the `serve` command:

```python
@app.command()
def openapi(
    output: Path = typer.Option(
        None, "--output", "-o", help="Write to this file instead of stdout."
    ),
    format: str = typer.Option(
        "swagger2",
        "--format",
        help="openapi3 for the native document, swagger2 for Power Platform.",
    ),
) -> None:
    """Print the API description. Power Platform connectors need swagger2."""
    import json

    if format not in ("openapi3", "swagger2"):
        typer.secho(
            "error: format must be openapi3 or swagger2", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1)
    try:
        from docsift.api.app import create_app
        from docsift.api.swagger2 import to_swagger2
    except ImportError as exc:
        typer.secho(
            "error: the API extra is not installed; "
            "install it with: pip install 'docsift[api]'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    document = create_app().openapi()
    if format == "swagger2":
        document = to_swagger2(document)
    text = json.dumps(document, indent=2)
    if output is None:
        typer.echo(text)
    else:
        Path(output).write_text(text + "\n", encoding="utf-8")
        typer.echo(f"wrote {output}")
```

Add to `tests/unit/test_swagger2.py`:

```python
def test_cli_writes_a_swagger2_file(tmp_path):
    from typer.testing import CliRunner

    from docsift.cli.main import app

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    target = tmp_path / "connector.json"
    result = runner.invoke(app, ["openapi", "--output", str(target)])
    assert result.exit_code == 0, result.output
    import json

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["swagger"] == "2.0"
    validate(document)


def test_cli_rejects_an_unknown_format():
    from typer.testing import CliRunner

    from docsift.cli.main import app

    runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
    result = runner.invoke(app, ["openapi", "--format", "yaml"])
    assert result.exit_code == 1
```

- [ ] **Step 7: Run the full gate and CI parity**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`, then the docling-free run, then `uv run pytest tests/unit/test_lazy_imports.py -v` to confirm the new module did not break the import guard.
Expected: 310 passed, 7 deselected, ruff clean.

- [ ] **Step 8: Commit**

```bash
git add src/docsift/api/swagger2.py src/docsift/cli/main.py pyproject.toml uv.lock tests/unit/test_swagger2.py
git commit -m "feat: emit a Swagger 2.0 document for Power Platform connectors"
```

---

### Task 4: n8n example workflow

**Files:**
- Create: `examples/n8n/docsift-convert-and-search.json`, `examples/n8n/README.md`
- Test: `tests/unit/test_examples.py`

**Interfaces:**
- Consumes: the API's endpoints and the `X-API-Key` header from Task 2.
- Produces: an n8n workflow JSON importable via *Workflows → Import from File*, implementing upload → poll → search, plus a README explaining the three values a user must set.
- A test asserts the workflow's URLs and methods match the real routes, so the example cannot rot silently when a route changes.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_examples.py`:

```python
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
        (EXAMPLES / "n8n" / "docsift-convert-and-search.json").read_text(
            encoding="utf-8"
        )
    )
    assert workflow["name"]
    assert isinstance(workflow["nodes"], list)
    assert len(workflow["nodes"]) >= 4
    assert "connections" in workflow


def test_n8n_workflow_calls_only_real_endpoints():
    workflow = json.loads(
        (EXAMPLES / "n8n" / "docsift-convert-and-search.json").read_text(
            encoding="utf-8"
        )
    )
    routes = _routes()
    template_paths = {
        path.replace("{document_id}", "").replace("{job_id}", "")
        for _, path in routes
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
            tail.startswith(prefix) or prefix.rstrip("/") in tail
            for prefix in template_paths
        ), f"workflow calls an endpoint that does not exist: {tail}"


def test_n8n_workflow_polls_before_searching():
    workflow = json.loads(
        (EXAMPLES / "n8n" / "docsift-convert-and-search.json").read_text(
            encoding="utf-8"
        )
    )
    names = [node["name"] for node in workflow["nodes"]]
    assert any("poll" in name.lower() or "job" in name.lower() for name in names)
    assert any("search" in name.lower() for name in names)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_examples.py -v`
Expected: FAIL — the examples directory does not exist.

- [ ] **Step 3: Write the workflow**

`examples/n8n/docsift-convert-and-search.json`:

```json
{
  "name": "DocSift: convert and search a document",
  "nodes": [
    {
      "parameters": {},
      "id": "start-node",
      "name": "When clicking Test workflow",
      "type": "n8n-nodes-base.manualTrigger",
      "typeVersion": 1,
      "position": [0, 0]
    },
    {
      "parameters": {
        "assignments": {
          "assignments": [
            {
              "id": "base-url",
              "name": "baseUrl",
              "value": "http://127.0.0.1:8000",
              "type": "string"
            },
            {
              "id": "api-key",
              "name": "apiKey",
              "value": "",
              "type": "string"
            },
            {
              "id": "query",
              "name": "query",
              "value": "operational risk",
              "type": "string"
            }
          ]
        },
        "options": {}
      },
      "id": "settings-node",
      "name": "Settings",
      "type": "n8n-nodes-base.set",
      "typeVersion": 3.4,
      "position": [200, 0]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "={{ $json.baseUrl }}/v1/documents",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            { "name": "X-API-Key", "value": "={{ $json.apiKey }}" }
          ]
        },
        "contentType": "multipart-form-data",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            { "parameterType": "formBinaryData", "name": "file", "inputDataFieldName": "data" }
          ]
        },
        "options": {}
      },
      "id": "upload-node",
      "name": "Upload document",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [400, 0]
    },
    {
      "parameters": { "amount": 5, "unit": "seconds" },
      "id": "wait-node",
      "name": "Wait before polling",
      "type": "n8n-nodes-base.wait",
      "typeVersion": 1.1,
      "position": [600, 0]
    },
    {
      "parameters": {
        "url": "={{ $('Settings').item.json.baseUrl }}/v1/jobs/{{ $('Upload document').item.json.job_id }}",
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            { "name": "X-API-Key", "value": "={{ $('Settings').item.json.apiKey }}" }
          ]
        },
        "options": {}
      },
      "id": "poll-node",
      "name": "Poll job status",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [800, 0]
    },
    {
      "parameters": {
        "conditions": {
          "options": { "caseSensitive": true, "version": 2 },
          "conditions": [
            {
              "leftValue": "={{ $json.status }}",
              "rightValue": "succeeded",
              "operator": { "type": "string", "operation": "equals" }
            }
          ],
          "combinator": "and"
        },
        "options": {}
      },
      "id": "if-node",
      "name": "Conversion finished?",
      "type": "n8n-nodes-base.if",
      "typeVersion": 2.2,
      "position": [1000, 0]
    },
    {
      "parameters": {
        "url": "={{ $('Settings').item.json.baseUrl }}/v1/documents/{{ $('Upload document').item.json.document_id }}/search",
        "sendQuery": true,
        "queryParameters": {
          "parameters": [
            { "name": "q", "value": "={{ $('Settings').item.json.query }}" },
            { "name": "limit", "value": "5" },
            { "name": "max_tokens", "value": "5000" }
          ]
        },
        "sendHeaders": true,
        "headerParameters": {
          "parameters": [
            { "name": "X-API-Key", "value": "={{ $('Settings').item.json.apiKey }}" }
          ]
        },
        "options": {}
      },
      "id": "search-node",
      "name": "Search document",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4.2,
      "position": [1200, -100]
    }
  ],
  "connections": {
    "When clicking Test workflow": {
      "main": [[{ "node": "Settings", "type": "main", "index": 0 }]]
    },
    "Settings": {
      "main": [[{ "node": "Upload document", "type": "main", "index": 0 }]]
    },
    "Upload document": {
      "main": [[{ "node": "Wait before polling", "type": "main", "index": 0 }]]
    },
    "Wait before polling": {
      "main": [[{ "node": "Poll job status", "type": "main", "index": 0 }]]
    },
    "Poll job status": {
      "main": [[{ "node": "Conversion finished?", "type": "main", "index": 0 }]]
    },
    "Conversion finished?": {
      "main": [
        [{ "node": "Search document", "type": "main", "index": 0 }],
        [{ "node": "Wait before polling", "type": "main", "index": 0 }]
      ]
    }
  },
  "settings": { "executionOrder": "v1" },
  "pinData": {}
}
```

Note the false branch of the IF node loops back to the wait node — that is the polling loop, and it is why this workflow survives a conversion that takes minutes.

- [ ] **Step 4: Write the example README**

`examples/n8n/README.md`:

```markdown
# DocSift in n8n

`docsift-convert-and-search.json` uploads a document, waits for conversion to
finish, then runs a keyword search and returns the matching chunks.

## Import

n8n → **Workflows** → **Import from File** → choose the JSON.

## Set three values in the "Settings" node

| Field | What to put |
|---|---|
| `baseUrl` | Where DocSift is reachable, e.g. `https://docsift.internal` |
| `apiKey` | Your `DOCSIFT_API_KEY`, or leave empty if the service has none |
| `query` | The search query to run once conversion finishes |

## Supply the document

The **Upload document** node sends the binary field named `data`. Put any node
that produces a binary file before it — *Read Binary File*, an email
attachment, a webhook upload — or use n8n's *Edit Fields* node to attach one for
testing.

## How the polling loop works

Conversion runs in the background and can take minutes on a long PDF, so the
workflow waits five seconds, checks the job, and loops back if it is not
finished. The **Conversion finished?** node's false branch returns to the wait
node. That loop is the whole reason this workflow is more than two HTTP calls —
an integration that assumes conversion is instant will fail on real documents.

If a job fails, the loop keeps polling. Add a second condition on
`{{ $json.status }} equals failed` if you want to break out and handle errors.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_examples.py -v && uv run pytest -q`
Expected: 3 passed in the new file; the full suite green.

- [ ] **Step 6: Commit**

```bash
git add examples/n8n tests/unit/test_examples.py
git commit -m "docs: add an importable n8n convert-and-search workflow"
```

---

### Task 5: Copilot Studio and Power Automate instructions

**Files:**
- Create: `examples/copilot-studio/README.md`, `examples/power-automate/README.md`
- Modify: `tests/unit/test_examples.py`

**Interfaces:**
- Consumes: `docsift openapi --format swagger2` from Task 3, the API key from Task 2.
- Produces: step-by-step connector instructions and a Power Automate flow description. A test asserts both documents reference the real operation ids, so renaming an operation breaks the test rather than silently invalidating the instructions.

**The honest constraint this task must document:** Copilot Studio actions call a connector operation once. They cannot poll a loop. So the recommended shape is:

- **Search** — call the connector directly from Copilot Studio. It is fast and synchronous, and it is the operation an agent actually needs at conversation time.
- **Upload and wait** — use a Power Automate flow with a *Do until* loop, called from Copilot Studio if the agent must ingest a document mid-conversation. The PRD's "no Power Automate intermediary required" holds for the connector itself, which imports and works standalone; it does not hold for polling, and the instructions must say so rather than implying a single action can wait for a long conversion.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_examples.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_examples.py -v`
Expected: the four new tests FAIL — the example directories do not exist.

- [ ] **Step 3: Write the Copilot Studio instructions**

`examples/copilot-studio/README.md`:

```markdown
# DocSift as a Copilot Studio custom connector

## 1. Generate the connector file

Power Platform custom connectors take **Swagger 2.0**. DocSift's live
`/openapi.json` is OpenAPI 3.1 and will not import, so generate the Swagger 2.0
version:

    DOCSIFT_PUBLIC_URL=https://docsift.internal docsift openapi --format swagger2 -o docsift-connector.json

Set `DOCSIFT_PUBLIC_URL` to the address Power Platform will call. It becomes the
connector's host, and a connector pointing at `127.0.0.1` will fail from the
cloud.

## 2. Create the connector

1. Go to **Power Apps** → **Custom connectors** → **New custom connector** →
   **Import an OpenAPI file**.
2. Upload `docsift-connector.json`.
3. On the **Security** tab, choose **API Key**, parameter label `API Key`,
   parameter name `X-API-Key`, location `Header`. (Skip this only if the service
   runs with no `DOCSIFT_API_KEY`, which means anyone who reaches the URL can
   use it.)
4. **Create connector**, then **Test** with a connection using your key.

## 3. Use it from Copilot Studio

In your agent: **Actions** → **Add an action** → **Connector** → your DocSift
connector.

**Add `searchDocument` first.** It is the operation an agent actually needs
during a conversation: it returns only the chunks relevant to a question,
already token-budgeted, with page and section metadata for citation. It answers
in milliseconds, well inside connector timeouts.

Give the action inputs the agent can fill: `document_id` from your own record of
the document, and `q` from the user's question.

## 4. Uploading documents needs a Power Automate flow

A Copilot Studio action calls a connector operation **once**. It cannot loop.
DocSift conversion is asynchronous — `uploadDocument` returns a job id
immediately and `getJobStatus` must be polled until it reports `succeeded`,
which can take minutes on a long PDF.

So:

- **Search from Copilot Studio directly.** One call, fast, no loop needed.
- **Upload via a Power Automate flow** with a *Do until* loop, and call that flow
  from Copilot Studio if the agent must ingest a document mid-conversation. See
  `../power-automate/README.md`.

Trying to make a single Copilot Studio action wait for a conversion will hit the
connector timeout (roughly 120 seconds) on exactly the large documents this tool
exists to handle.

## Operation reference

| Operation | Use it for |
|---|---|
| `searchDocument` | Answering a question about a known document — start here |
| `uploadDocument` | Starting a conversion; returns a job id, does not wait |
| `getJobStatus` | Polling until conversion finishes |
| `getDocumentChunks` | Retrieving every chunk when you genuinely need the whole document |
| `getDocumentMarkdown` | Retrieving the whole document as text |
| `deleteDocument` | Removing a document, its index and its cached copies |
```

- [ ] **Step 4: Write the Power Automate instructions**

`examples/power-automate/README.md`:

```markdown
# DocSift in Power Automate

A flow that uploads a document, waits for conversion, and returns the search
results — the polling wrapper a Copilot Studio action cannot do on its own.

## Prerequisite

The custom connector from `../copilot-studio/README.md`. Create it once; both
Power Automate and Copilot Studio use the same connector.

## Flow shape

1. **Trigger** — whatever suits you: *When a file is created* in SharePoint or
   OneDrive, a manual trigger, or *When Copilot Studio calls a flow*.

2. **DocSift — uploadDocument**
   - `file`: the file content from the trigger.
   - `engine`: leave as `auto`.
   - Outputs: `job_id`, `document_id`.

3. **Initialize variable** — name `jobStatus`, type String, value `queued`.

4. **Do until** — condition: `jobStatus` **is equal to** `succeeded`.
   Set *Limits* to a count of 60 and a timeout of `PT30M`, so a slow document
   does not spin forever.
   Inside the loop:
   - **Delay** — 5 seconds. (Without this the loop burns its iteration count in
     seconds and gives up before conversion finishes.)
   - **DocSift — getJobStatus** with `job_id` from step 2.
   - **Set variable** `jobStatus` to the `status` output.
   - **Condition** — if `jobStatus` is equal to `failed`, **Terminate** the flow
     as Failed with the job's `error` value. Without this the loop runs to its
     limit on a failed conversion.

5. **DocSift — searchDocument**
   - `document_id`: from step 2.
   - `q`: your query.
   - `limit`: 5. `max_tokens`: 5000.

6. **Respond** — return the `results` array. Each entry carries `text`,
   `section_path`, `pages` and `score`, which is enough to answer with citations.

## Why the loop

Conversion runs in the background. `uploadDocument` returning does not mean the
document is ready — it means it is queued. A flow that fetches the result
immediately after uploading will get a 404 or an unfinished job on any document
large enough to matter.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_examples.py -v && uv run pytest -q`
Expected: 7 passed in the examples file; the full suite green.

- [ ] **Step 6: Commit**

```bash
git add examples/copilot-studio examples/power-automate tests/unit/test_examples.py
git commit -m "docs: add Copilot Studio connector and Power Automate flow guides"
```

---

### Task 6: Docs, release prep, and M6 exit verification

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `pyproject.toml`, `src/docsift/__init__.py`, `docs/specs/v0.1-spec.md`

**Interfaces:**
- Consumes: everything above.
- Produces: version `0.4.0`, a changelog entry, README coverage of the connector workflow and the API key, and verified exit criteria.

- [ ] **Step 1: Bump the version**

`pyproject.toml`: `version = "0.4.0"`. `src/docsift/__init__.py`: `__version__ = "0.4.0"`. Run `uv sync`, then `uv run pytest tests/test_package.py -v` (the version-agreement test added in the 0.3.0 release must pass).

- [ ] **Step 2: Write the CHANGELOG entry**

Insert above the 0.3.0 entry:

```markdown
## 0.4.0 — 2026-08-05

Makes DocSift usable from Copilot Studio, Power Automate and n8n.

- New `docsift openapi --format swagger2` emits a **Swagger 2.0** document.
  Power Platform custom connectors do not accept the OpenAPI 3.1 document the
  service serves at `/openapi.json`, so this is what you import.
- New optional API key. Set `DOCSIFT_API_KEY` and every `/v1/*` route requires an
  `X-API-Key` header; `/health`, `/version` and `/openapi.json` stay open.
  **Off by default** — an existing deployment that sets nothing behaves exactly
  as before. This is a single shared secret, not per-user identity.
- Every API operation now carries a summary and a description written for agent
  tool selection, including when to prefer search over retrieving a whole
  document.
- The OpenAPI document declares a `servers` entry, set with `DOCSIFT_PUBLIC_URL`
  (default `http://127.0.0.1:8000`). A connector needs a reachable host.
- New `examples/`: an importable n8n workflow that uploads, polls and searches;
  Copilot Studio custom connector instructions; and a Power Automate flow with
  the *Do until* polling loop.

**A Copilot Studio action cannot poll.** Search works as a direct connector call.
Uploading needs a Power Automate flow to wait for conversion — the examples
explain the split rather than pretending one action can wait minutes.
```

- [ ] **Step 3: Update the README**

Add after the HTTP API section:

```markdown
## Connecting Copilot Studio, Power Automate and n8n

    DOCSIFT_PUBLIC_URL=https://docsift.internal docsift openapi --format swagger2 -o docsift-connector.json

Import that file as a Power Platform custom connector. The service's own
`/openapi.json` is OpenAPI 3.1, which custom connectors do not accept — this
command emits the Swagger 2.0 they need.

Worked guides live in `examples/`:

- `examples/n8n/` — a workflow you can import directly: upload, poll, search.
- `examples/copilot-studio/` — connector setup and which operations to expose.
- `examples/power-automate/` — the *Do until* flow that waits for conversion.

## Protecting the service

Set `DOCSIFT_API_KEY` and every `/v1/*` route requires an `X-API-Key` header:

    DOCSIFT_API_KEY=your-shared-secret docsift serve
    curl -H "X-API-Key: your-shared-secret" http://127.0.0.1:8000/v1/documents/...

`/health`, `/version` and `/openapi.json` stay open so container health checks
and connector imports keep working. This is one shared secret for the whole
service — not per-user identity, and no substitute for network controls. If you
set nothing, the service behaves exactly as it did before.
```

Update the Known limitations section: replace any line saying the API has no authentication with an accurate one, and add the connector caveat:

```markdown
- The API's optional `DOCSIFT_API_KEY` is a single shared secret. There is no
  per-user identity, no rate limiting and no multi-tenancy — keep the service on
  infrastructure you control.
- A Copilot Studio action cannot poll a long-running conversion. Search works as
  a direct connector call; uploading needs a Power Automate flow with a
  *Do until* loop (see `examples/`).
```

Also update `docs/specs/v0.1-spec.md` if it still lists FR-15 or search as unimplemented.

- [ ] **Step 4: Verify the M6 exit criteria**

Run these and record the output:

```bash
export DOCSIFT_DATA_DIR=/tmp/m6-data DOCSIFT_CACHE_DIR=/tmp/m6-cache
DOCSIFT_PUBLIC_URL=https://docsift.example.com uv run docsift openapi --format swagger2 -o /tmp/m6-connector.json
uv run python -c "
import json
from openapi_spec_validator import validate
d = json.load(open('/tmp/m6-connector.json'))
validate(d)
print('valid swagger:', d['swagger'], 'host:', d['host'], 'schemes:', d['schemes'])
print('operations:', sorted(o['operationId'] for p in d['paths'].values() for o in p.values()))
"
DOCSIFT_API_KEY=test-secret uv run docsift serve --port 8791 &
sleep 8
echo "no key:   $(curl -sS -o /dev/null -w '%{http_code}' -F file=@tests/fixtures/sample.pdf http://127.0.0.1:8791/v1/documents)"
echo "with key: $(curl -sS -F file=@tests/fixtures/sample.pdf -H 'X-API-Key: test-secret' http://127.0.0.1:8791/v1/documents)"
echo "health:   $(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8791/health)"
pkill -f "docsift serve --port 8791"
```

Expected: the Swagger 2.0 file validates, reports `host: docsift.example.com` and `schemes: ['https']`, and lists all nine operations; the unauthenticated upload returns **401**; the authenticated one returns **202**; `/health` returns **200** without a key.

Then walk the n8n workflow's calls manually with curl in the same sequence (upload → poll → search) against a running server, to prove the sequence the example encodes actually works.

**State plainly in your report what could not be verified here:** nobody has imported the file into a real Power Platform tenant, and no Copilot Studio agent has called it. Those need the user's tenant. Do not claim the exit criteria are met beyond what you actually ran.

- [ ] **Step 5: Run every gate**

```bash
uv run pytest -v
uv run pytest tests/integration -m integration -v
uv run ruff check . && uv run ruff format --check .
uv build
tar -tzf dist/docsift-0.4.0.tar.gz | grep -E 'superpowers|code-review-graph|CLAUDE' && echo LEAK || echo "sdist clean"
```

plus the docling-free CI-parity run. Confirm neither `~/.cache/docsift` nor `~/.local/share/docsift` was touched.

**Decide and report:** should `examples/` ship inside the sdist? It is small and genuinely useful to someone who installs from PyPI, but the current sdist include list omits it. Recommend one way and say why.

- [ ] **Step 6: Commit**

```bash
git add README.md CHANGELOG.md pyproject.toml uv.lock src/docsift/__init__.py docs/specs/v0.1-spec.md
git commit -m "chore: document workflow integrations and prepare v0.4.0"
```

*(Controller then runs the whole-branch review, pushes, confirms CI, and asks about publishing.)*

---

## Self-review notes

- **Exit-criteria coverage.** "An n8n HTTP workflow can upload and search a document" — Task 4, verified by curl-walking the same sequence in Task 6. "The OpenAPI file imports successfully into a Power Platform custom connector" — Task 3 produces the file and validates it against the Swagger 2.0 schema; the actual tenant import is the user's step and Task 6 requires saying so. "A Copilot Studio action can upload, poll, and retrieve selected chunks within connector timeout limits" — Task 5 documents the only shape that actually satisfies this (direct search, Power Automate for upload+poll) rather than asserting a single action can wait.
- **Deliverable coverage.** n8n example (4); Copilot Studio instructions (5); Power Automate example (5); operation names and descriptions optimized for agent tools — FR-15 (1), plus the Swagger 2.0 emitter (3) without which none of the connector deliverables function.
- **Scope judgement.** The API key is not in the PRD's M6 deliverable list, and "enterprise authentication" is an explicit non-goal. It is included because this is the milestone that publishes the service's URL into other people's tools, and a single shared secret is the smallest thing that makes that safe. It is off by default so it changes nothing for existing users. If the reviewer or the product owner disagrees, Task 2 can be dropped without affecting Tasks 1, 3, 4 or 6 — only the security step in Task 5's instructions would need a note.
- **Known risk.** The Swagger 2.0 converter handles the constructs this API uses today and raises `UnsupportedConstructError` on anything else. That is deliberate: a silent partial conversion produces a connector file that fails inside Microsoft's wizard with an unhelpful error, whereas a raised exception fails at generation time with a named cause. The test suite pins the current shape; a new route using a new construct will fail the test rather than ship broken.
- **Type consistency.** `to_swagger2` and `UnsupportedConstructError` (Task 3) are used with those names in Task 3's CLI and Task 6's verification; `DOCSIFT_PUBLIC_URL` (Task 1) is consumed by Tasks 3, 5 and 6; `X-API-Key` and `DOCSIFT_API_KEY` (Task 2) appear identically in Tasks 4, 5 and 6; the nine `operationId` values are referenced consistently across Tasks 1, 3, 4 and 5.
- **Untestable here, stated as such.** No Power Platform tenant and no n8n instance exist in this environment. Task 6 requires the report to distinguish what was executed from what was only validated structurally — the same discipline applied to the unbuilt Dockerfile in Milestone 4.
