# DocSift M0+M1: Bootstrap and Two-Engine Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pip-installable `docsift` CLI that converts a real PDF (or Office/HTML file) into normalized Markdown + JSON through either Docling or MarkItDown behind one engine interface.

**Architecture:** src-layout Python package. Engine adapters (`engines/`) implement one `ConversionEngine` ABC and are loaded lazily through a registry; a pure-function router maps file type → engine name; `services/conversion_service.py` orchestrates validate → route → convert → normalize → write, producing the engine-neutral `ConversionResult` schema from `core/models.py`. Typer CLI on top.

**Tech Stack:** Python 3.12, uv, Typer, Pydantic v2, Docling (optional extra), MarkItDown (optional extra), pytest, Ruff, GitHub Actions.

## Global Constraints

- Python `>=3.11`, developed on 3.12. Dependency manager: `uv` only (never pip/poetry directly).
- Package name `docsift`, src layout (`src/docsift/`), CLI entry point `docsift`.
- Engines are optional extras: `docsift[docling]`, `docsift[markitdown]`, `docsift[all]`. Core install must work with neither.
- Engine imports must be lazy (inside methods / `is_available`). `docsift --help` must succeed with no engines installed.
- No engine-specific types outside `engines/`. Downstream code sees only `core.models` types.
- All PDFs route to Docling in auto mode. MarkItDown converts PDFs only on explicit selection.
- Never log or print document contents.
- License MIT. Conventional commits (`feat:`, `test:`, `chore:`, `ci:`). Run from repo root: `/Users/anish/DocBridge/docsift`.
- Integration tests (real engine conversions) carry `@pytest.mark.integration` and are excluded by default via pytest `addopts`; CI runs unit tests + MarkItDown-dependent tests only (Docling is too heavy for CI at this stage).

---

### Task 1: Repository bootstrap

**Files:**
- Create: `.gitignore`, `LICENSE`, `README.md`, `pyproject.toml`
- Create: `src/docsift/__init__.py`, `src/docsift/py.typed`
- Test: `tests/test_package.py`

**Interfaces:**
- Produces: importable package `docsift` with `__version__: str = "0.1.0.dev0"`; `uv run pytest` and `uv run ruff check .` working.

- [ ] **Step 1: Initialize git and base files**

```bash
cd /Users/anish/DocBridge/docsift
git init -b main
```

Create `.gitignore`:

```gitignore
__pycache__/
*.pyc
.venv/
dist/
build/
*.egg-info/
.pytest_cache/
.ruff_cache/
output/
.env
.DS_Store
```

Create `LICENSE` with the standard MIT license text, copyright line:

```text
MIT License

Copyright (c) 2026 Anish Monci Varghese

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Create `README.md`:

```markdown
# DocSift

> Convert documents once. Give agents only what they need.

DocSift converts PDFs and Office documents into clean, structured, AI-ready
Markdown and JSON — locally, with no cloud APIs. Docling handles PDFs;
MarkItDown handles the breadth formats; both sit behind one interface.

Status: pre-release (v0.1 in development). See `docs/specs/v0.1-spec.md`.

## Install (development)

    uv sync --all-extras

## Usage

    uv run docsift convert report.pdf
    uv run docsift convert report.pdf --engine markitdown
    uv run docsift --version

## License

MIT
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[project]
name = "docsift"
version = "0.1.0.dev0"
description = "Convert documents once. Give agents only what they need."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Anish Monci Varghese" }]
dependencies = [
  "typer>=0.12",
  "pydantic>=2.7",
]

[project.optional-dependencies]
markitdown = ["markitdown[docx,pptx,xlsx]>=0.1.1"]
docling = ["docling>=2.0"]
all = ["docsift[markitdown]", "docsift[docling]"]

[project.scripts]
docsift = "docsift.cli.main:app"

[dependency-groups]
dev = [
  "pytest>=8.0",
  "ruff>=0.5",
  "fpdf2>=2.7",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/docsift"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: needs real conversion engines (may download models)"]
addopts = "-m 'not integration'"
```

- [ ] **Step 3: Write the failing test**

`tests/test_package.py`:

```python
import re

from docsift import __version__


def test_version_is_semver_like():
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.\w+)?", __version__)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv sync && uv run pytest tests/test_package.py -v`
Expected: FAIL / collection error — `docsift` has no `__version__` (package empty).

- [ ] **Step 5: Write minimal implementation**

`src/docsift/__init__.py`:

```python
__version__ = "0.1.0.dev0"
```

Create empty marker file `src/docsift/py.typed`.

- [ ] **Step 6: Run tests and lint to verify they pass**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: 1 passed; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: bootstrap docsift package with uv, ruff, pytest"
```

---

### Task 2: Core models and exceptions

**Files:**
- Create: `src/docsift/core/__init__.py` (empty), `src/docsift/core/models.py`, `src/docsift/core/exceptions.py`
- Test: `tests/unit/test_models.py`, `tests/unit/__init__.py` (empty)

**Interfaces:**
- Produces (exact, later tasks depend on these):
  - `core.exceptions`: `DocSiftError(Exception)`, `UnsupportedFileError(DocSiftError)`, `EngineNotAvailableError(DocSiftError)`, `ConversionFailedError(DocSiftError)`
  - `core.models`: Pydantic v2 models `ConversionWarning(code: str, message: str)`, `SourceMetadata(filename: str, media_type: str, size_bytes: int, sha256: str)`, `ConversionMetadata(engine: str, engine_version: str, docsift_version: str, selection_reason: str, started_at: datetime, completed_at: datetime, duration_ms: int, ocr_used: bool = False, cached: bool = False)`, `DocumentContent(title: str | None = None, page_count: int | None = None, language: str | None = None, markdown: str)`, `ConversionMetrics(characters: int, words: int, estimated_tokens: int)`, `Chunk(chunk_id: str, text: str, estimated_tokens: int = 0, section_path: list[str] = [], pages: list[int] = [])`, `EngineOutput(markdown: str, title: str | None = None, page_count: int | None = None, ocr_used: bool = False, engine_version: str, warnings: list[ConversionWarning] = [])`, `ConversionResult(document_id: str, source: SourceMetadata, conversion: ConversionMetadata, document: DocumentContent, chunks: list[Chunk] = [], metrics: ConversionMetrics, warnings: list[ConversionWarning] = [])`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_models.py`:

```python
from datetime import UTC, datetime

from docsift.core.models import (
    ConversionMetadata,
    ConversionMetrics,
    ConversionResult,
    DocumentContent,
    SourceMetadata,
)


def _result() -> ConversionResult:
    now = datetime.now(UTC)
    return ConversionResult(
        document_id="doc_abc123def456",
        source=SourceMetadata(
            filename="report.pdf",
            media_type="application/pdf",
            size_bytes=1234,
            sha256="a" * 64,
        ),
        conversion=ConversionMetadata(
            engine="docling",
            engine_version="2.0.0",
            docsift_version="0.1.0.dev0",
            selection_reason="PDF routes to Docling",
            started_at=now,
            completed_at=now,
            duration_ms=10,
        ),
        document=DocumentContent(markdown="# Hi"),
        metrics=ConversionMetrics(characters=4, words=2, estimated_tokens=1),
    )


def test_result_defaults():
    result = _result()
    assert result.chunks == []
    assert result.warnings == []
    assert result.conversion.ocr_used is False
    assert result.conversion.cached is False


def test_result_json_round_trip():
    result = _result()
    restored = ConversionResult.model_validate_json(result.model_dump_json())
    assert restored == result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.core`.

- [ ] **Step 3: Write minimal implementation**

`src/docsift/core/exceptions.py`:

```python
class DocSiftError(Exception):
    """Base class for all DocSift errors."""


class UnsupportedFileError(DocSiftError):
    """The input file is missing, empty, too large, or of an unsupported type."""


class EngineNotAvailableError(DocSiftError):
    """The requested conversion engine is unknown or not installed."""


class ConversionFailedError(DocSiftError):
    """The engine raised while converting the document."""
```

`src/docsift/core/models.py`:

```python
from datetime import datetime

from pydantic import BaseModel, Field


class ConversionWarning(BaseModel):
    code: str
    message: str


class SourceMetadata(BaseModel):
    filename: str
    media_type: str
    size_bytes: int
    sha256: str


class ConversionMetadata(BaseModel):
    engine: str
    engine_version: str
    docsift_version: str
    selection_reason: str
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    ocr_used: bool = False
    cached: bool = False


class DocumentContent(BaseModel):
    title: str | None = None
    page_count: int | None = None
    language: str | None = None
    markdown: str


class ConversionMetrics(BaseModel):
    characters: int
    words: int
    estimated_tokens: int


class Chunk(BaseModel):
    chunk_id: str
    text: str
    estimated_tokens: int = 0
    section_path: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)


class EngineOutput(BaseModel):
    """Raw, engine-agnostic output of a single engine run, pre-normalization."""

    markdown: str
    title: str | None = None
    page_count: int | None = None
    ocr_used: bool = False
    engine_version: str
    warnings: list[ConversionWarning] = Field(default_factory=list)


class ConversionResult(BaseModel):
    document_id: str
    source: SourceMetadata
    conversion: ConversionMetadata
    document: DocumentContent
    chunks: list[Chunk] = Field(default_factory=list)
    metrics: ConversionMetrics
    warnings: list[ConversionWarning] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_models.py -v && uv run ruff check .`
Expected: 2 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/core tests/unit
git commit -m "feat: add engine-neutral result schema and exception hierarchy"
```

---

### Task 3: Token estimator (fallback heuristic)

**Files:**
- Create: `src/docsift/processing/__init__.py` (empty), `src/docsift/processing/token_estimator.py`
- Test: `tests/unit/test_token_estimator.py`

**Interfaces:**
- Produces: `estimate_tokens(text: str) -> int` — character-ratio heuristic (chars/4, minimum 1 for non-empty text, 0 for empty). tiktoken replaces the internals in Milestone 3; the signature stays.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_token_estimator.py`:

```python
from docsift.processing.token_estimator import estimate_tokens


def test_empty_text_is_zero_tokens():
    assert estimate_tokens("") == 0


def test_four_chars_per_token_heuristic():
    assert estimate_tokens("a" * 400) == 100


def test_short_text_is_at_least_one_token():
    assert estimate_tokens("Hi") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_token_estimator.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.processing`.

- [ ] **Step 3: Write minimal implementation**

`src/docsift/processing/token_estimator.py`:

```python
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Approximate token count. Heuristic (len/4) until tiktoken lands in M3."""
    if not text:
        return 0
    return max(1, round(len(text) / _CHARS_PER_TOKEN))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_token_estimator.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/processing tests/unit/test_token_estimator.py
git commit -m "feat: add heuristic token estimator"
```

---

### Task 4: Engine interface and registry

**Files:**
- Create: `src/docsift/engines/__init__.py` (empty), `src/docsift/engines/base.py`, `src/docsift/engines/registry.py`
- Test: `tests/unit/test_registry.py`

**Interfaces:**
- Consumes: `EngineOutput`, `EngineNotAvailableError` from Task 2.
- Produces:
  - `engines.base.ConversionEngine` (ABC): class attr `name: ClassVar[str]`; `@classmethod is_available(cls) -> bool`; `convert(self, path: Path) -> EngineOutput`.
  - `engines.registry`: `get_engine(name: str) -> ConversionEngine`, `register_engine(name: str, cls: type[ConversionEngine]) -> None`, `unregister_engine(name: str) -> None`, `available_engines() -> list[str]`. Built-in names `"docling"` and `"markitdown"` resolve lazily by import path; `register_engine` overrides them (used by tests and future plugins). `get_engine` raises `EngineNotAvailableError` for unknown names and for engines whose `is_available()` is False, with an install hint (`uv pip install 'docsift[<name>]'`).

- [ ] **Step 1: Write the failing test**

`tests/unit/test_registry.py`:

```python
from pathlib import Path

import pytest

from docsift.core.exceptions import EngineNotAvailableError
from docsift.core.models import EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import get_engine, register_engine, unregister_engine


class FakeEngine(ConversionEngine):
    name = "fake"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path) -> EngineOutput:
        return EngineOutput(markdown="# fake", engine_version="0.0.1")


class UnavailableEngine(FakeEngine):
    name = "ghost"

    @classmethod
    def is_available(cls) -> bool:
        return False


@pytest.fixture
def fake_engine():
    register_engine("fake", FakeEngine)
    yield
    unregister_engine("fake")


def test_get_registered_engine_returns_instance(fake_engine):
    engine = get_engine("fake")
    assert isinstance(engine, FakeEngine)
    assert engine.convert(Path("x.pdf")).markdown == "# fake"


def test_unknown_engine_raises():
    with pytest.raises(EngineNotAvailableError, match="unknown engine"):
        get_engine("nope")


def test_unavailable_engine_raises_with_install_hint():
    register_engine("ghost", UnavailableEngine)
    try:
        with pytest.raises(EngineNotAvailableError, match="docsift\\[ghost\\]"):
            get_engine("ghost")
    finally:
        unregister_engine("ghost")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.engines`.

- [ ] **Step 3: Write minimal implementation**

`src/docsift/engines/base.py`:

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from docsift.core.models import EngineOutput


class ConversionEngine(ABC):
    """One document-conversion backend. Implementations keep their imports lazy."""

    name: ClassVar[str]

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """True when the engine's optional dependency is importable."""

    @abstractmethod
    def convert(self, path: Path) -> EngineOutput:
        """Convert the file at `path`. Raises on failure; never returns None."""
```

`src/docsift/engines/registry.py`:

```python
import importlib

from docsift.core.exceptions import EngineNotAvailableError
from docsift.engines.base import ConversionEngine

_BUILTIN_PATHS: dict[str, str] = {
    "docling": "docsift.engines.docling_engine:DoclingEngine",
    "markitdown": "docsift.engines.markitdown_engine:MarkItDownEngine",
}
_registered: dict[str, type[ConversionEngine]] = {}


def register_engine(name: str, cls: type[ConversionEngine]) -> None:
    _registered[name] = cls


def unregister_engine(name: str) -> None:
    _registered.pop(name, None)


def available_engines() -> list[str]:
    return sorted(set(_BUILTIN_PATHS) | set(_registered))


def _resolve(name: str) -> type[ConversionEngine]:
    if name in _registered:
        return _registered[name]
    if name in _BUILTIN_PATHS:
        module_path, _, attr = _BUILTIN_PATHS[name].partition(":")
        module = importlib.import_module(module_path)
        return getattr(module, attr)
    raise EngineNotAvailableError(f"unknown engine '{name}'; expected one of {available_engines()}")


def get_engine(name: str) -> ConversionEngine:
    cls = _resolve(name)
    if not cls.is_available():
        raise EngineNotAvailableError(
            f"engine '{name}' is not installed; install it with: uv pip install 'docsift[{name}]'"
        )
    return cls()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_registry.py -v && uv run ruff check .`
Expected: 3 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/engines tests/unit/test_registry.py
git commit -m "feat: add ConversionEngine interface and lazy engine registry"
```

---

### Task 5: File-type router

**Files:**
- Create: `src/docsift/engines/router.py`
- Test: `tests/unit/test_router.py`

**Interfaces:**
- Consumes: `UnsupportedFileError`, `EngineNotAvailableError` from Task 2.
- Produces: `engines.router.select_engine_name(path: Path, requested: str = "auto") -> tuple[str, str]` returning `(engine_name, reason)`; module constants `DOCLING_SUFFIXES: set[str]`, `MARKITDOWN_SUFFIXES: set[str]`, `SUPPORTED_SUFFIXES: set[str]`, `VALID_ENGINE_CHOICES = {"auto", "docling", "markitdown"}`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_router.py`:

```python
from pathlib import Path

import pytest

from docsift.core.exceptions import EngineNotAvailableError, UnsupportedFileError
from docsift.engines.router import select_engine_name


def test_pdf_routes_to_docling():
    engine, reason = select_engine_name(Path("report.PDF"))
    assert engine == "docling"
    assert "PDF" in reason


@pytest.mark.parametrize("name", ["a.docx", "b.pptx", "c.xlsx", "d.html", "e.csv", "f.epub"])
def test_office_and_web_formats_route_to_markitdown(name):
    engine, _ = select_engine_name(Path(name))
    assert engine == "markitdown"


def test_explicit_selection_wins_over_routing():
    engine, reason = select_engine_name(Path("report.pdf"), requested="markitdown")
    assert engine == "markitdown"
    assert reason == "explicit user selection"


def test_unsupported_suffix_raises():
    with pytest.raises(UnsupportedFileError, match="unsupported file type"):
        select_engine_name(Path("movie.mp4"))


def test_unknown_engine_choice_raises():
    with pytest.raises(EngineNotAvailableError, match="unknown engine"):
        select_engine_name(Path("report.pdf"), requested="pandoc")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_router.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.engines.router`.

- [ ] **Step 3: Write minimal implementation**

`src/docsift/engines/router.py`:

```python
from pathlib import Path

from docsift.core.exceptions import EngineNotAvailableError, UnsupportedFileError

DOCLING_SUFFIXES: set[str] = {".pdf"}
MARKITDOWN_SUFFIXES: set[str] = {
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".xml",
    ".zip",
    ".epub",
    ".txt",
    ".md",
}
SUPPORTED_SUFFIXES: set[str] = DOCLING_SUFFIXES | MARKITDOWN_SUFFIXES
VALID_ENGINE_CHOICES: set[str] = {"auto", "docling", "markitdown"}


def select_engine_name(path: Path, requested: str = "auto") -> tuple[str, str]:
    """Pick an engine for `path`. Returns (engine_name, human-readable reason)."""
    if requested not in VALID_ENGINE_CHOICES:
        raise EngineNotAvailableError(
            f"unknown engine '{requested}'; expected one of {sorted(VALID_ENGINE_CHOICES)}"
        )
    if requested != "auto":
        return requested, "explicit user selection"
    suffix = path.suffix.lower()
    if suffix in DOCLING_SUFFIXES:
        return "docling", "PDF always routes to Docling"
    if suffix in MARKITDOWN_SUFFIXES:
        return "markitdown", f"'{suffix}' routes to MarkItDown"
    raise UnsupportedFileError(
        f"unsupported file type '{suffix}'; supported: {sorted(SUPPORTED_SUFFIXES)}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_router.py -v`
Expected: 9 passed (parametrized).

- [ ] **Step 5: Commit**

```bash
git add src/docsift/engines/router.py tests/unit/test_router.py
git commit -m "feat: add file-type engine router (PDF->Docling, breadth->MarkItDown)"
```

---

### Task 6: MarkItDown adapter with fixtures

**Files:**
- Create: `src/docsift/engines/markitdown_engine.py`, `tests/fixtures/sample.html`
- Test: `tests/unit/test_markitdown_engine.py`

**Interfaces:**
- Consumes: `ConversionEngine`, `EngineOutput`, `ConversionFailedError`.
- Produces: `MarkItDownEngine(ConversionEngine)` with `name = "markitdown"`. All `markitdown` imports stay inside methods.

- [ ] **Step 1: Create the HTML fixture**

`tests/fixtures/sample.html`:

```html
<html>
  <head><title>Sample document</title></head>
  <body>
    <h1>Hello DocSift</h1>
    <p>This is a tiny fixture used to exercise the MarkItDown engine.</p>
  </body>
</html>
```

- [ ] **Step 2: Write the failing test**

`tests/unit/test_markitdown_engine.py`:

```python
from pathlib import Path

import pytest

pytest.importorskip("markitdown")

from docsift.engines.markitdown_engine import MarkItDownEngine  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_is_available_when_installed():
    assert MarkItDownEngine.is_available() is True


def test_converts_html_to_markdown():
    output = MarkItDownEngine().convert(FIXTURES / "sample.html")
    assert "Hello DocSift" in output.markdown
    assert output.engine_version
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv sync --extra markitdown && uv run pytest tests/unit/test_markitdown_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.engines.markitdown_engine`.

- [ ] **Step 4: Write minimal implementation**

`src/docsift/engines/markitdown_engine.py`:

```python
from importlib import metadata, util
from pathlib import Path

from docsift.core.exceptions import ConversionFailedError
from docsift.core.models import EngineOutput
from docsift.engines.base import ConversionEngine


class MarkItDownEngine(ConversionEngine):
    """Adapter for microsoft/markitdown. Imports stay lazy."""

    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return util.find_spec("markitdown") is not None

    def convert(self, path: Path) -> EngineOutput:
        from markitdown import MarkItDown

        try:
            result = MarkItDown().convert(str(path))
        except Exception as exc:
            # Exception text can quote document content; expose only the type name.
            raise ConversionFailedError(
                f"markitdown failed on '{path.name}': {type(exc).__name__}"
            ) from exc
        return EngineOutput(
            markdown=result.text_content or "",
            title=getattr(result, "title", None),
            engine_version=metadata.version("markitdown"),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_markitdown_engine.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/docsift/engines/markitdown_engine.py tests/unit/test_markitdown_engine.py tests/fixtures/sample.html
git commit -m "feat: add MarkItDown engine adapter"
```

---

### Task 7: Docling adapter with generated PDF fixture

**Files:**
- Create: `src/docsift/engines/docling_engine.py`, `scripts/make_fixtures.py`, `tests/fixtures/sample.pdf` (generated)
- Test: `tests/integration/test_docling_engine.py`, `tests/integration/__init__.py` (empty)

**Interfaces:**
- Consumes: `ConversionEngine`, `EngineOutput`, `ConversionFailedError`.
- Produces: `DoclingEngine(ConversionEngine)` with `name = "docling"`. All `docling` imports stay inside methods. First real run downloads Docling's layout models (hundreds of MB) — that is why this test is `@pytest.mark.integration` and excluded by default.

- [ ] **Step 1: Write the fixture generator and generate the PDF**

`scripts/make_fixtures.py`:

```python
"""Generate binary test fixtures. Run: uv run python scripts/make_fixtures.py"""

from pathlib import Path

from fpdf import FPDF


def main() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=16)
    pdf.cell(text="Hello DocSift")
    pdf.ln(12)
    pdf.set_font("helvetica", size=12)
    pdf.cell(text="This one-page PDF exercises the Docling engine.")
    out = Path(__file__).parent.parent / "tests" / "fixtures" / "sample.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
```

Run: `uv run python scripts/make_fixtures.py`
Expected: `wrote .../tests/fixtures/sample.pdf` and the file exists (a few KB).

- [ ] **Step 2: Write the failing test**

`tests/integration/test_docling_engine.py`:

```python
from pathlib import Path

import pytest

pytest.importorskip("docling")

from docsift.engines.docling_engine import DoclingEngine  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"

pytestmark = pytest.mark.integration


def test_is_available_when_installed():
    assert DoclingEngine.is_available() is True


def test_converts_pdf_to_markdown():
    output = DoclingEngine().convert(FIXTURES / "sample.pdf")
    assert "Hello DocSift" in output.markdown
    assert output.page_count == 1
    assert output.engine_version
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv sync --all-extras && uv run pytest tests/integration -m integration -v`
Expected: FAIL — `ModuleNotFoundError: docsift.engines.docling_engine`.

- [ ] **Step 4: Write minimal implementation**

`src/docsift/engines/docling_engine.py`:

```python
from importlib import metadata, util
from pathlib import Path

from docsift.core.exceptions import ConversionFailedError
from docsift.core.models import EngineOutput
from docsift.engines.base import ConversionEngine


class DoclingEngine(ConversionEngine):
    """Adapter for IBM docling. Imports stay lazy; first run downloads models."""

    name = "docling"

    @classmethod
    def is_available(cls) -> bool:
        return util.find_spec("docling") is not None

    def convert(self, path: Path) -> EngineOutput:
        from docling.document_converter import DocumentConverter

        try:
            result = DocumentConverter().convert(str(path))
            document = result.document
            markdown = document.export_to_markdown()
        except Exception as exc:
            # Exception text can quote document content; expose only the type name.
            raise ConversionFailedError(
                f"docling failed on '{path.name}': {type(exc).__name__}"
            ) from exc
        page_count = len(document.pages) if getattr(document, "pages", None) else None
        return EngineOutput(
            markdown=markdown,
            title=getattr(document, "name", None),
            page_count=page_count,
            engine_version=metadata.version("docling"),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration -m integration -v`
Expected: 2 passed (first run is slow — model download). Also confirm the default run still excludes them: `uv run pytest -v` shows the integration tests as deselected.

- [ ] **Step 6: Commit**

```bash
git add src/docsift/engines/docling_engine.py tests/integration scripts/make_fixtures.py tests/fixtures/sample.pdf
git commit -m "feat: add Docling engine adapter with generated PDF fixture"
```

---

### Task 8: Conversion service

**Files:**
- Create: `src/docsift/services/__init__.py` (empty), `src/docsift/services/conversion_service.py`
- Test: `tests/unit/test_conversion_service.py`

**Interfaces:**
- Consumes: `select_engine_name` (Task 5), `get_engine`/`register_engine`/`unregister_engine` (Task 4), `estimate_tokens` (Task 3), all `core.models` types, `docsift.__version__`.
- Produces: `services.conversion_service.convert_document(path: Path, engine: str = "auto", output_dir: Path | None = None) -> ConversionResult`. Validates (exists, non-empty, ≤ `MAX_FILE_SIZE_BYTES` = 50 MB), hashes, routes, converts, normalizes, and — when `output_dir` is given — writes `<stem>.md` and `<stem>.docsift.json` there. `document_id` is `"doc_" + sha256[:12]`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_conversion_service.py`:

```python
from pathlib import Path

import pytest

from docsift.core.exceptions import UnsupportedFileError
from docsift.core.models import ConversionResult, EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine
from docsift.services.conversion_service import convert_document


class StubEngine(ConversionEngine):
    name = "markitdown"  # registered over the builtin for these tests

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path) -> EngineOutput:
        return EngineOutput(markdown="# Stubbed\n\nHello.", engine_version="9.9.9")


@pytest.fixture
def stub_engine():
    register_engine("markitdown", StubEngine)
    yield
    unregister_engine("markitdown")


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    file = tmp_path / "note.txt"
    file.write_text("hello world", encoding="utf-8")
    return file


def test_returns_normalized_result(stub_engine, text_file):
    result = convert_document(text_file)
    assert isinstance(result, ConversionResult)
    assert result.document_id.startswith("doc_")
    assert len(result.document_id) == 4 + 12
    assert result.conversion.engine == "markitdown"
    assert result.conversion.engine_version == "9.9.9"
    assert result.conversion.selection_reason
    assert result.document.markdown == "# Stubbed\n\nHello."
    assert result.metrics.estimated_tokens >= 1
    assert result.source.sha256 == result.source.sha256.lower()
    assert len(result.source.sha256) == 64


def test_writes_markdown_and_json(stub_engine, text_file, tmp_path):
    out = tmp_path / "out"
    result = convert_document(text_file, output_dir=out)
    md = out / "note.md"
    js = out / "note.docsift.json"
    assert md.read_text(encoding="utf-8") == result.document.markdown
    assert ConversionResult.model_validate_json(js.read_text(encoding="utf-8")) == result


def test_missing_file_raises(tmp_path):
    with pytest.raises(UnsupportedFileError, match="not a file"):
        convert_document(tmp_path / "ghost.pdf")


def test_empty_file_raises(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.touch()
    with pytest.raises(UnsupportedFileError, match="empty"):
        convert_document(empty)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_conversion_service.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.services`.

- [ ] **Step 3: Write minimal implementation**

`src/docsift/services/conversion_service.py`:

```python
import hashlib
import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from docsift import __version__
from docsift.core.exceptions import ConversionFailedError, DocSiftError, UnsupportedFileError
from docsift.core.models import (
    ConversionMetadata,
    ConversionMetrics,
    ConversionResult,
    DocumentContent,
    SourceMetadata,
)
from docsift.engines.registry import get_engine
from docsift.engines.router import select_engine_name
from docsift.processing.token_estimator import estimate_tokens

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate(path: Path) -> int:
    if not path.is_file():
        raise UnsupportedFileError(f"not a file: {path}")
    size = path.stat().st_size
    if size == 0:
        raise UnsupportedFileError(f"file is empty: {path}")
    if size > MAX_FILE_SIZE_BYTES:
        raise UnsupportedFileError(
            f"file is {size} bytes; maximum is {MAX_FILE_SIZE_BYTES} (50 MB)"
        )
    return size


def convert_document(
    path: Path, engine: str = "auto", output_dir: Path | None = None
) -> ConversionResult:
    path = Path(path)
    size = _validate(path)
    engine_name, reason = select_engine_name(path, engine)
    engine_impl = get_engine(engine_name)
    sha = _sha256(path)

    started = datetime.now(UTC)
    try:
        output = engine_impl.convert(path)
    except DocSiftError:
        raise
    except Exception as exc:  # engine bugs must surface as structured errors
        # Exception text can quote document content; expose only the type name.
        raise ConversionFailedError(
            f"{engine_name} failed on '{path.name}': {type(exc).__name__}"
        ) from exc
    completed = datetime.now(UTC)

    markdown = output.markdown
    result = ConversionResult(
        document_id=f"doc_{sha[:12]}",
        source=SourceMetadata(
            filename=path.name,
            media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            size_bytes=size,
            sha256=sha,
        ),
        conversion=ConversionMetadata(
            engine=engine_name,
            engine_version=output.engine_version,
            docsift_version=__version__,
            selection_reason=reason,
            started_at=started,
            completed_at=completed,
            duration_ms=int((completed - started).total_seconds() * 1000),
            ocr_used=output.ocr_used,
        ),
        document=DocumentContent(
            title=output.title,
            page_count=output.page_count,
            markdown=markdown,
        ),
        metrics=ConversionMetrics(
            characters=len(markdown),
            words=len(markdown.split()),
            estimated_tokens=estimate_tokens(markdown),
        ),
        warnings=list(output.warnings),
    )

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{path.stem}.md").write_text(markdown, encoding="utf-8")
        (output_dir / f"{path.stem}.docsift.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_conversion_service.py -v && uv run ruff check .`
Expected: 4 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/services tests/unit/test_conversion_service.py
git commit -m "feat: add conversion service (validate, route, convert, normalize, write)"
```

---

### Task 9: Typer CLI

**Files:**
- Create: `src/docsift/cli/__init__.py` (empty), `src/docsift/cli/main.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `convert_document` (Task 8), `DocSiftError`, `__version__`.
- Produces: Typer app object `docsift.cli.main:app` (matches the `[project.scripts]` entry from Task 1). Commands: `docsift --version`, `docsift convert PATH [--engine auto|docling|markitdown] [--output DIR]`. Errors print `error: <message>` to stderr and exit 1; document contents are never printed.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_cli.py`:

```python
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docsift import __version__
from docsift.cli.main import app
from docsift.core.models import EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine

runner = CliRunner()


class StubEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path) -> EngineOutput:
        return EngineOutput(markdown="# Stubbed", engine_version="9.9.9")


@pytest.fixture
def stub_engine():
    register_engine("markitdown", StubEngine)
    yield
    unregister_engine("markitdown")


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"docsift {__version__}" in result.output


def test_convert_help_mentions_engine_option():
    result = runner.invoke(app, ["convert", "--help"])
    assert result.exit_code == 0
    assert "--engine" in result.output


def test_convert_writes_output(stub_engine, tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(app, ["convert", str(source), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert "document_id: doc_" in result.output
    assert (out / "note.md").exists()
    assert (out / "note.docsift.json").exists()


def test_convert_unsupported_file_exits_nonzero(tmp_path):
    source = tmp_path / "movie.mp4"
    source.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(source)])
    assert result.exit_code == 1
    assert "unsupported file type" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.cli.main`.

- [ ] **Step 3: Write minimal implementation**

`src/docsift/cli/main.py`:

```python
from pathlib import Path

import typer

from docsift import __version__

app = typer.Typer(
    help="DocSift — convert documents once, give agents only what they need.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"docsift {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the DocSift version and exit.",
    ),
) -> None:
    """DocSift command-line interface."""


@app.command()
def convert(
    path: Path = typer.Argument(..., help="File to convert."),
    engine: str = typer.Option("auto", help="Engine: auto, docling, or markitdown."),
    output: Path = typer.Option(Path("output"), help="Directory for Markdown and JSON."),
) -> None:
    """Convert a document to clean Markdown plus a normalized JSON result."""
    from docsift.core.exceptions import DocSiftError
    from docsift.services.conversion_service import convert_document

    try:
        result = convert_document(path, engine=engine, output_dir=output)
    except DocSiftError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"document_id: {result.document_id}")
    typer.echo(f"engine: {result.conversion.engine} ({result.conversion.selection_reason})")
    typer.echo(f"estimated_tokens: {result.metrics.estimated_tokens}")
    typer.echo(f"markdown: {output / (path.stem + '.md')}")
    typer.echo(f"result_json: {output / (path.stem + '.docsift.json')}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: 4 passed.

- [ ] **Step 5: Verify the installed entry point (Milestone 0 exit criterion)**

Run: `uv run docsift --help && uv run docsift --version`
Expected: help text and `docsift 0.1.0.dev0`.

- [ ] **Step 6: Commit**

```bash
git add src/docsift/cli tests/unit/test_cli.py
git commit -m "feat: add Typer CLI with version and convert commands"
```

---

### Task 10: CI workflow and M1 exit-criteria verification

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md` (usage section already written in Task 1 — verify it matches reality, fix if not)

**Interfaces:**
- Consumes: everything above.
- Produces: green CI on GitHub; verified M0+M1 exit criteria.

- [ ] **Step 1: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: uv sync --extra markitdown
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest -v
```

- [ ] **Step 2: Run the full local gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -v`
Expected: all clean, all tests pass, integration tests deselected.

- [ ] **Step 3: Verify Milestone 1 exit criteria with real engines**

```bash
uv sync --all-extras
uv run docsift convert tests/fixtures/sample.pdf --engine docling --output /tmp/docsift-check
uv run docsift convert tests/fixtures/sample.pdf --engine markitdown --output /tmp/docsift-check2
uv run docsift convert tests/fixtures/sample.html --output /tmp/docsift-check3
```

Expected: each command exits 0, prints a `doc_…` id, and produces a `.md` + `.docsift.json` pair containing "Hello DocSift". (First Docling run downloads models — allow several minutes.)

- [ ] **Step 4: Commit**

```bash
git add .github README.md
git commit -m "ci: add GitHub Actions workflow (ruff + pytest on 3.11/3.12)"
```

- [ ] **Step 5: Create the GitHub repository and push** *(needs user's say-so on repo visibility — ask before pushing)*

```bash
gh repo create docsift --private --source . --push
```

Expected: repo exists, CI runs green on GitHub.

---

## Self-review notes

- Spec coverage: M0 exit criteria (uv sync / pytest / `docsift --help`) land in Tasks 1 and 9; M1 exit criteria (both engines convert `sample.pdf` to Markdown + metadata JSON) land in Tasks 6–8 and are verified end-to-end in Task 10 Step 3. FR-02 partial validation (exists/empty/size) is in Task 8 by design — MIME sniffing and corruption detection are M2 scope per the spec.
- The `StubEngine` in Tasks 8 and 9 is deliberately duplicated so each test file stands alone.
- Type consistency: `EngineOutput` (Task 2) is consumed identically by Tasks 4, 6, 7, 8, 9; `select_engine_name` returns `tuple[str, str]` everywhere; registry function names (`get_engine`, `register_engine`, `unregister_engine`) match across Tasks 4, 8, 9.
