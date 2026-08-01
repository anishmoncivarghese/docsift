# DocSift M2: Comparison Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docsift compare report.pdf` runs both engines on one document and produces a machine-readable comparison JSON plus a human-readable Markdown report, capturing per-engine failures without stopping.

**Architecture:** Two pre-M2 refactors first (schema_version on ConversionResult; engine choices derived from the registry). Then: a pure markdown-metrics module (heading/table counts), new `EngineRunSummary`/`ComparisonResult` models, a `comparison_service` that reuses `convert_document` per engine and never lets one engine's failure abort the other, a report renderer, and the `docsift compare` CLI command. Benchmark corpus = small generated fixture PDFs per category + a manifest/fetch-script pattern for licensed real-world documents (corpus itself is never committed).

**Tech Stack:** Same as M1 — Python 3.12, uv, Typer, Pydantic v2, pytest, Ruff. No new dependencies.

## Global Constraints

- Everything from the M0+M1 plan still binds: uv only; lazy engine imports; no engine types outside `engines/`; PDFs→Docling in auto mode; **never log or print document contents (error text exposes only exception type names for non-DocSiftError failures)**; conventional commits; integration tests marked and excluded by default.
- Do NOT modify this plan file from an implementer subagent (no checkbox ticking) — the controller owns it.
- Comparison must not raise when one engine fails (M2 exit criterion); it may raise for invalid input files (unsupported type, too large, missing) since no engine could run.
- Repo root: `/Users/anish/DocBridge/docsift`. Current HEAD at plan time: `5f11a88`.

---

### Task 1: Pre-M2 refactors — schema_version and registry-derived engine choices

**Files:**
- Modify: `src/docsift/core/models.py` (ConversionResult), `src/docsift/engines/router.py`
- Test: `tests/unit/test_models.py`, `tests/unit/test_router.py`

**Interfaces:**
- Consumes: existing `ConversionResult`, `available_engines()` from `docsift.engines.registry`.
- Produces: `ConversionResult.schema_version: str = "1"` (new field, default, serialized in JSON). Router: `valid_engine_choices() -> set[str]` returning `{"auto"} | set(available_engines())`; `select_engine_name` validates against it. The module constant `VALID_ENGINE_CHOICES` is REMOVED (Task 4's service and the CLI never referenced it; only router internals and tests did).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_models.py`:

```python
def test_result_carries_schema_version():
    result = _result()
    assert result.schema_version == "1"
    assert '"schema_version":"1"' in result.model_dump_json().replace(" ", "")
```

Append to `tests/unit/test_router.py`:

```python
def test_registered_engine_becomes_valid_choice():
    from docsift.engines.registry import register_engine, unregister_engine
    from tests.unit.test_registry import FakeEngine

    register_engine("fake", FakeEngine)
    try:
        engine, reason = select_engine_name(Path("report.pdf"), requested="fake")
    finally:
        unregister_engine("fake")
    assert engine == "fake"
    assert reason == "explicit user selection"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_models.py tests/unit/test_router.py -v`
Expected: 2 new FAIL (`schema_version` missing; `fake` rejected as unknown engine), existing tests pass.

- [ ] **Step 3: Implement**

In `src/docsift/core/models.py`, add as the FIRST field of `ConversionResult`:

```python
class ConversionResult(BaseModel):
    schema_version: str = "1"
    document_id: str
    ...
```

In `src/docsift/engines/router.py`: delete `VALID_ENGINE_CHOICES`, add an import and function, and use it:

```python
from docsift.engines.registry import available_engines


def valid_engine_choices() -> set[str]:
    """Engine names accepted by --engine: 'auto' plus every registered/built-in engine."""
    return {"auto"} | set(available_engines())
```

and in `select_engine_name`, replace the membership check:

```python
    choices = valid_engine_choices()
    if requested not in choices:
        raise EngineNotAvailableError(
            f"unknown engine '{requested}'; expected one of {sorted(choices)}"
        )
```

- [ ] **Step 4: Run the full unit suite**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: all pass (44 + 2 new), ruff clean. (No import cycle: registry does not import router.)

- [ ] **Step 5: Commit**

```bash
git add src/docsift/core/models.py src/docsift/engines/router.py tests/unit/test_models.py tests/unit/test_router.py
git commit -m "feat: add schema_version to results and derive engine choices from registry"
```

---

### Task 2: Markdown metrics module

**Files:**
- Create: `src/docsift/processing/markdown_metrics.py`
- Test: `tests/unit/test_markdown_metrics.py`

**Interfaces:**
- Produces: `count_headings(markdown: str) -> int` (lines matching `#{1,6}` + space at line start) and `count_tables(markdown: str) -> int` (number of maximal runs of consecutive lines that start with `|`). Pure functions, stdlib only.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_markdown_metrics.py`:

```python
from docsift.processing.markdown_metrics import count_headings, count_tables

DOC = """# Title

## Section one

Text with # not a heading mid-line.

|h1|h2|
|--|--|
|a|b|

More text.

| x | y |
| - | - |
| 1 | 2 |
| 3 | 4 |

### Deep heading
"""


def test_counts_headings():
    assert count_headings(DOC) == 3


def test_counts_table_blocks():
    assert count_tables(DOC) == 2


def test_empty_markdown():
    assert count_headings("") == 0
    assert count_tables("") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_markdown_metrics.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`src/docsift/processing/markdown_metrics.py`:

```python
import re

_HEADING = re.compile(r"^#{1,6} ", re.MULTILINE)


def count_headings(markdown: str) -> int:
    """Number of ATX headings (lines starting with 1-6 '#' plus a space)."""
    return len(_HEADING.findall(markdown))


def count_tables(markdown: str) -> int:
    """Number of table blocks: maximal runs of consecutive lines starting with '|'."""
    tables = 0
    in_table = False
    for line in markdown.splitlines():
        is_row = line.lstrip().startswith("|")
        if is_row and not in_table:
            tables += 1
        in_table = is_row
    return tables
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_markdown_metrics.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/processing/markdown_metrics.py tests/unit/test_markdown_metrics.py
git commit -m "feat: add markdown heading and table counters"
```

---

### Task 3: Comparison models

**Files:**
- Modify: `src/docsift/core/models.py`
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Consumes: `SourceMetadata`.
- Produces (exact — Tasks 4–6 depend on these):

```python
class EngineRunSummary(BaseModel):
    engine: str
    success: bool
    engine_version: str | None = None
    error: str | None = None
    duration_ms: int | None = None
    characters: int | None = None
    words: int | None = None
    estimated_tokens: int | None = None
    heading_count: int | None = None
    table_count: int | None = None
    warning_count: int = 0
    ocr_used: bool = False
    markdown_path: str | None = None
    result_json_path: str | None = None


class ComparisonResult(BaseModel):
    schema_version: str = "1"
    source: SourceMetadata
    docsift_version: str
    created_at: datetime
    runs: list[EngineRunSummary] = Field(default_factory=list)
```

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_models.py`:

```python
def test_comparison_result_round_trip():
    from docsift.core.models import ComparisonResult, EngineRunSummary

    comparison = ComparisonResult(
        source=SourceMetadata(
            filename="report.pdf",
            media_type="application/pdf",
            size_bytes=10,
            sha256="b" * 64,
        ),
        docsift_version="0.1.0.dev0",
        created_at=datetime.now(UTC),
        runs=[
            EngineRunSummary(engine="docling", success=True, estimated_tokens=10),
            EngineRunSummary(engine="markitdown", success=False, error="ConversionFailedError"),
        ],
    )
    restored = ComparisonResult.model_validate_json(comparison.model_dump_json())
    assert restored == comparison
    assert restored.runs[1].success is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: FAIL — `ImportError: ComparisonResult`.

- [ ] **Step 3: Implement**

Add both classes (exactly as in the Interfaces block above) to `src/docsift/core/models.py`, after `ConversionResult`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_models.py -v && uv run ruff check .`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/core/models.py tests/unit/test_models.py
git commit -m "feat: add comparison result models"
```

---

### Task 4: Comparison service

**Files:**
- Modify: `src/docsift/services/conversion_service.py` (extract one public helper)
- Create: `src/docsift/services/comparison_service.py`
- Test: `tests/unit/test_comparison_service.py`

**Interfaces:**
- Consumes: `convert_document`, models from Task 3, `count_headings`/`count_tables` from Task 2.
- Produces:
  - `conversion_service.build_source_metadata(path: Path) -> SourceMetadata` — extracted from the body of `convert_document` (which now calls it); public so the comparison works even when every engine fails.
  - `comparison_service.compare_document(path: Path, output_dir: Path | None = None, engines: Sequence[str] = ("docling", "markitdown")) -> ComparisonResult`. Per engine: calls `convert_document(path, engine=name, output_dir=output_dir / name if output_dir else None)`; on success fills the summary from the result + markdown metrics; on `DocSiftError` records `error=str(exc)` (our error messages are content-safe by construction); on any other exception records `error=type(exc).__name__` only. One engine's failure never stops the others. Input validation errors that no engine could survive (missing/empty/oversized/unsupported file) DO raise — validated once up front via `_validate`-equivalent behavior by calling `build_source_metadata` after a validation call; simplest correct form shown in Step 3.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_comparison_service.py`:

```python
from pathlib import Path

import pytest

from docsift.core.exceptions import ConversionFailedError, UnsupportedFileError
from docsift.core.models import ComparisonResult, EngineOutput
from docsift.engines.base import ConversionEngine
from docsift.engines.registry import register_engine, unregister_engine
from docsift.services.comparison_service import compare_document


class GoodEngine(ConversionEngine):
    name = "markitdown"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def convert(self, path: Path) -> EngineOutput:
        return EngineOutput(markdown="# Title\n\n|a|b|\n|-|-|\n", engine_version="1.0.0")


class BadEngine(GoodEngine):
    name = "docling"

    def convert(self, path: Path) -> EngineOutput:
        raise ConversionFailedError("docling failed on 'note.txt': BoomError")


@pytest.fixture
def engines():
    register_engine("markitdown", GoodEngine)
    register_engine("docling", BadEngine)
    yield
    unregister_engine("markitdown")
    unregister_engine("docling")


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    file = tmp_path / "note.txt"
    file.write_text("hello world", encoding="utf-8")
    return file


def test_failure_of_one_engine_does_not_stop_comparison(engines, text_file):
    comparison = compare_document(text_file)
    assert isinstance(comparison, ComparisonResult)
    by_engine = {run.engine: run for run in comparison.runs}
    assert by_engine["markitdown"].success is True
    assert by_engine["markitdown"].heading_count == 1
    assert by_engine["markitdown"].table_count == 1
    assert by_engine["markitdown"].estimated_tokens >= 1
    assert by_engine["docling"].success is False
    assert "BoomError" in by_engine["docling"].error


def test_writes_comparison_artifacts(engines, text_file, tmp_path):
    out = tmp_path / "cmp"
    comparison = compare_document(text_file, output_dir=out)
    assert (out / "note.compare.json").exists()
    assert (out / "note.compare.md").exists()
    md_run = next(run for run in comparison.runs if run.engine == "markitdown")
    assert md_run.markdown_path is not None
    assert Path(md_run.markdown_path).exists()


def test_invalid_input_raises_before_any_engine_runs(engines, tmp_path):
    bad = tmp_path / "movie.mp4"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFileError):
        compare_document(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_comparison_service.py -v`
Expected: FAIL — `ModuleNotFoundError: docsift.services.comparison_service`.

- [ ] **Step 3: Implement**

In `src/docsift/services/conversion_service.py`, extract the source-metadata construction into a public function and call it from `convert_document` (behavior unchanged):

```python
def build_source_metadata(path: Path) -> SourceMetadata:
    """Validate `path` and describe it. Raises UnsupportedFileError for bad inputs."""
    path = Path(path)
    size = _validate(path)
    return SourceMetadata(
        filename=path.name,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        size_bytes=size,
        sha256=_sha256(path),
    )
```

(`convert_document` now begins with `source = build_source_metadata(path)` and uses `source.sha256`/`source.size_bytes` where it previously computed them inline. Keep the engine-resolution-before-hash ordering benefit by calling `select_engine_name` + `get_engine` BEFORE `build_source_metadata` — resolve engine first, then validate+hash, as today.)

`src/docsift/services/comparison_service.py`:

```python
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from docsift import __version__
from docsift.core.exceptions import DocSiftError
from docsift.core.models import ComparisonResult, EngineRunSummary
from docsift.processing.markdown_metrics import count_headings, count_tables
from docsift.services.conversion_service import build_source_metadata, convert_document

DEFAULT_ENGINES: tuple[str, ...] = ("docling", "markitdown")


def _run_engine(path: Path, engine: str, output_dir: Path | None) -> EngineRunSummary:
    try:
        result = convert_document(path, engine=engine, output_dir=output_dir)
    except DocSiftError as exc:
        return EngineRunSummary(engine=engine, success=False, error=str(exc))
    except Exception as exc:  # never leak content; expose only the type name
        return EngineRunSummary(engine=engine, success=False, error=type(exc).__name__)
    markdown = result.document.markdown
    return EngineRunSummary(
        engine=engine,
        success=True,
        engine_version=result.conversion.engine_version,
        duration_ms=result.conversion.duration_ms,
        characters=result.metrics.characters,
        words=result.metrics.words,
        estimated_tokens=result.metrics.estimated_tokens,
        heading_count=count_headings(markdown),
        table_count=count_tables(markdown),
        warning_count=len(result.warnings),
        ocr_used=result.conversion.ocr_used,
        markdown_path=str(output_dir / f"{path.stem}.md") if output_dir else None,
        result_json_path=str(output_dir / f"{path.stem}.docsift.json") if output_dir else None,
    )


def compare_document(
    path: Path,
    output_dir: Path | None = None,
    engines: Sequence[str] = DEFAULT_ENGINES,
) -> ComparisonResult:
    """Run every engine on `path`; one engine's failure never stops the others."""
    path = Path(path)
    source = build_source_metadata(path)  # raises for inputs no engine could handle

    runs = [
        _run_engine(path, engine, (Path(output_dir) / engine) if output_dir else None)
        for engine in engines
    ]
    comparison = ComparisonResult(
        source=source,
        docsift_version=__version__,
        created_at=datetime.now(UTC),
        runs=runs,
    )
    if output_dir is not None:
        from docsift.services.comparison_report import render_report

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{path.stem}.compare.json").write_text(
            comparison.model_dump_json(indent=2), encoding="utf-8"
        )
        (output_dir / f"{path.stem}.compare.md").write_text(
            render_report(comparison), encoding="utf-8"
        )
    return comparison
```

Note: `comparison_report` is created in Task 5. For THIS task's tests to pass, create it now as the minimal stub that Task 5 replaces with the real renderer — this is the one place a stub is acceptable, and Task 5's tests supersede it:

`src/docsift/services/comparison_report.py`:

```python
from docsift.core.models import ComparisonResult


def render_report(comparison: ComparisonResult) -> str:
    return f"# Comparison: {comparison.source.filename}\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_comparison_service.py tests/unit/test_conversion_service.py -v && uv run ruff check .`
Expected: all pass (the conversion-service refactor must not break its 6 existing tests), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/services tests/unit/test_comparison_service.py
git commit -m "feat: add comparison service running all engines fault-tolerantly"
```

---

### Task 5: Comparison report renderer

**Files:**
- Modify: `src/docsift/services/comparison_report.py` (replace Task 4's stub)
- Test: `tests/unit/test_comparison_report.py`

**Interfaces:**
- Consumes: `ComparisonResult`, `EngineRunSummary`.
- Produces: `render_report(comparison: ComparisonResult) -> str` — a Markdown document: title with filename, a metadata line (size, sha256 prefix, DocSift version, timestamp), then one table with a row per metric and a column per engine. Failed runs show `failed` in the status row and their error string in an "Errors" section below the table. Never includes document content — only metrics and filenames.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_comparison_report.py`:

```python
from datetime import UTC, datetime

from docsift.core.models import ComparisonResult, EngineRunSummary, SourceMetadata
from docsift.services.comparison_report import render_report


def _comparison() -> ComparisonResult:
    return ComparisonResult(
        source=SourceMetadata(
            filename="report.pdf",
            media_type="application/pdf",
            size_bytes=2048,
            sha256="c" * 64,
        ),
        docsift_version="0.1.0.dev0",
        created_at=datetime.now(UTC),
        runs=[
            EngineRunSummary(
                engine="docling",
                success=True,
                engine_version="2.117.0",
                duration_ms=1500,
                characters=900,
                words=150,
                estimated_tokens=225,
                heading_count=4,
                table_count=1,
            ),
            EngineRunSummary(
                engine="markitdown",
                success=False,
                error="markitdown failed on 'report.pdf': BoomError",
            ),
        ],
    )


def test_report_contains_metric_table_and_errors():
    report = render_report(_comparison())
    assert "# Comparison: report.pdf" in report
    assert "| metric | docling | markitdown |" in report
    assert "| status | ok | failed |" in report
    assert "| estimated_tokens | 225 | — |" in report
    assert "BoomError" in report
    assert "cccccccccccc" in report  # sha prefix shown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_comparison_report.py -v`
Expected: FAIL — stub renderer lacks the table.

- [ ] **Step 3: Implement**

Replace `src/docsift/services/comparison_report.py`:

```python
from docsift.core.models import ComparisonResult, EngineRunSummary

_METRICS: tuple[str, ...] = (
    "engine_version",
    "duration_ms",
    "characters",
    "words",
    "estimated_tokens",
    "heading_count",
    "table_count",
    "warning_count",
    "ocr_used",
)


def _cell(run: EngineRunSummary, metric: str) -> str:
    value = getattr(run, metric)
    return "—" if value is None else str(value)


def render_report(comparison: ComparisonResult) -> str:
    source = comparison.source
    lines = [
        f"# Comparison: {source.filename}",
        "",
        f"{source.size_bytes} bytes · sha256 {source.sha256[:12]} · "
        f"docsift {comparison.docsift_version} · {comparison.created_at.isoformat()}",
        "",
        "| metric | " + " | ".join(run.engine for run in comparison.runs) + " |",
        "|" + "---|" * (len(comparison.runs) + 1),
        "| status | "
        + " | ".join("ok" if run.success else "failed" for run in comparison.runs)
        + " |",
    ]
    for metric in _METRICS:
        lines.append(
            f"| {metric} | " + " | ".join(_cell(run, metric) for run in comparison.runs) + " |"
        )
    failures = [run for run in comparison.runs if not run.success]
    if failures:
        lines += ["", "## Errors", ""]
        lines += [f"- **{run.engine}**: {run.error}" for run in failures]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_comparison_report.py tests/unit/test_comparison_service.py -v`
Expected: all pass (Task 4's artifact test still passes with the real renderer).

- [ ] **Step 5: Commit**

```bash
git add src/docsift/services/comparison_report.py tests/unit/test_comparison_report.py
git commit -m "feat: render markdown comparison report"
```

---

### Task 6: CLI compare command

**Files:**
- Modify: `src/docsift/cli/main.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `compare_document` (Task 4).
- Produces: `docsift compare PATH [--output DIR]` (default `output`). Prints one line per engine (`engine: ok (duration_ms=…, estimated_tokens=…)` or `engine: failed (error…)`), then the two report paths. Exit code 0 if at least one engine succeeded; exit 1 if ALL runs failed or input validation failed. Service import stays inside the command function (lazy-import rule).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_cli.py` (reuse the file's existing runner and stub-registration style):

```python
def test_compare_reports_both_engines_and_exits_zero(tmp_path):
    from docsift.core.exceptions import ConversionFailedError

    class OkEngine(ConversionEngine):
        name = "markitdown"

        @classmethod
        def is_available(cls) -> bool:
            return True

        def convert(self, path: Path) -> EngineOutput:
            return EngineOutput(markdown="# Hi", engine_version="1.0")

    class FailEngine(OkEngine):
        name = "docling"

        def convert(self, path: Path) -> EngineOutput:
            raise ConversionFailedError("docling failed on 'note.txt': BoomError")

    register_engine("markitdown", OkEngine)
    register_engine("docling", FailEngine)
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    out = tmp_path / "cmp"
    try:
        result = runner.invoke(app, ["compare", str(source), "--output", str(out)])
    finally:
        unregister_engine("markitdown")
        unregister_engine("docling")
    assert result.exit_code == 0, result.output
    assert "markitdown: ok" in result.output
    assert "docling: failed" in result.output
    assert (out / "note.compare.json").exists()
    assert (out / "note.compare.md").exists()


def test_compare_exits_one_when_all_engines_fail(tmp_path):
    from docsift.core.exceptions import ConversionFailedError

    class FailEngine(ConversionEngine):
        name = "markitdown"

        @classmethod
        def is_available(cls) -> bool:
            return True

        def convert(self, path: Path) -> EngineOutput:
            raise ConversionFailedError("nope")

    class FailEngine2(FailEngine):
        name = "docling"

    register_engine("markitdown", FailEngine)
    register_engine("docling", FailEngine2)
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    try:
        result = runner.invoke(app, ["compare", str(source)])
    finally:
        unregister_engine("markitdown")
        unregister_engine("docling")
    assert result.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: 2 new FAIL — `compare` command missing.

- [ ] **Step 3: Implement**

Append to `src/docsift/cli/main.py`:

```python
@app.command()
def compare(
    path: Path = typer.Argument(..., help="File to run through every engine."),
    output: Path = typer.Option(Path("output"), help="Directory for per-engine and report files."),
) -> None:
    """Convert with every engine and write a comparison report."""
    from docsift.core.exceptions import DocSiftError
    from docsift.services.comparison_service import compare_document

    try:
        comparison = compare_document(path, output_dir=output)
    except DocSiftError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.secho(
            f"error: unexpected failure: {type(exc).__name__}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1) from exc

    for run in comparison.runs:
        if run.success:
            typer.echo(
                f"{run.engine}: ok (duration_ms={run.duration_ms}, "
                f"estimated_tokens={run.estimated_tokens})"
            )
        else:
            typer.echo(f"{run.engine}: failed ({run.error})")
    typer.echo(f"comparison_json: {output / (path.stem + '.compare.json')}")
    typer.echo(f"comparison_report: {output / (path.stem + '.compare.md')}")
    if not any(run.success for run in comparison.runs):
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli.py -v && uv run ruff check . && uv run ruff format .`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/docsift/cli/main.py tests/unit/test_cli.py
git commit -m "feat: add docsift compare command"
```

---

### Task 7: Fixture categories and benchmark manifest

**Files:**
- Modify: `scripts/make_fixtures.py`, `.gitignore`
- Create: `benchmarks/manifest.json`, `scripts/fetch_benchmarks.py`, `tests/fixtures/table.pdf`, `tests/fixtures/multipage.pdf` (generated)
- Test: `tests/integration/test_compare_integration.py`

**Interfaces:**
- Produces: two new generated fixture PDFs (`table.pdf` — one page with a 3×3 table; `multipage.pdf` — 3 pages of text); a benchmark manifest schema (`id`, `category`, `url`, `license`, `sha256` optional) seeded with one verifiable CC-BY entry; `scripts/fetch_benchmarks.py` downloading manifest entries into git-ignored `benchmarks/corpus/`.

- [ ] **Step 1: Extend the fixture generator**

Replace the body of `scripts/make_fixtures.py` `main()` with per-fixture functions:

```python
"""Generate binary test fixtures. Run: uv run python scripts/make_fixtures.py"""

from pathlib import Path

from fpdf import FPDF

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def make_sample() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=16)
    pdf.cell(text="Hello DocSift")
    pdf.ln(12)
    pdf.set_font("helvetica", size=12)
    pdf.cell(text="This one-page PDF exercises the Docling engine.")
    pdf.output(str(FIXTURES / "sample.pdf"))


def make_table() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(text="Quarterly results")
    pdf.ln(10)
    with pdf.table() as table:
        for row_data in (
            ("Quarter", "Revenue", "Costs"),
            ("Q1", "100", "60"),
            ("Q2", "120", "70"),
        ):
            row = table.row()
            for cell in row_data:
                row.cell(cell)
    pdf.output(str(FIXTURES / "table.pdf"))


def make_multipage() -> None:
    pdf = FPDF()
    pdf.set_font("helvetica", size=12)
    for page in range(1, 4):
        pdf.add_page()
        pdf.cell(text=f"Page {page} of the multipage DocSift fixture.")
    pdf.output(str(FIXTURES / "multipage.pdf"))


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    make_sample()
    make_table()
    make_multipage()
    print(f"wrote fixtures to {FIXTURES}")


if __name__ == "__main__":
    main()
```

Run: `uv run python scripts/make_fixtures.py`
Expected: three PDFs exist in tests/fixtures (sample.pdf regenerated — verify `uv run pytest tests/integration -m integration -v` still passes at Step 5, since its content assertion is unchanged).

- [ ] **Step 2: Write the benchmark manifest and fetch script**

`benchmarks/manifest.json`:

```json
{
  "schema_version": "1",
  "note": "Corpus files are downloaded to benchmarks/corpus/ (git-ignored). Only add documents whose license permits redistribution or direct download: CC-BY, public domain (e.g. US government works), or arXiv papers explicitly under CC licenses.",
  "documents": [
    {
      "id": "docling-technical-report",
      "category": "technical-report",
      "url": "https://arxiv.org/pdf/2408.09869",
      "license": "CC-BY-4.0",
      "source": "arXiv:2408.09869"
    }
  ]
}
```

`scripts/fetch_benchmarks.py`:

```python
"""Download benchmark corpus PDFs listed in benchmarks/manifest.json.

Run: uv run python scripts/fetch_benchmarks.py
Files land in benchmarks/corpus/ (git-ignored). Failures are reported, not fatal.
"""

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "benchmarks" / "manifest.json"
CORPUS = ROOT / "benchmarks" / "corpus"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    CORPUS.mkdir(parents=True, exist_ok=True)
    for doc in manifest["documents"]:
        target = CORPUS / f"{doc['id']}.pdf"
        if target.exists():
            print(f"exists: {target.name}")
            continue
        try:
            urllib.request.urlretrieve(doc["url"], target)
            print(f"fetched: {target.name}")
        except OSError as exc:
            print(f"FAILED {doc['id']}: {type(exc).__name__}")


if __name__ == "__main__":
    main()
```

Append to `.gitignore`:

```gitignore
benchmarks/corpus/
```

- [ ] **Step 3: Write the integration test**

`tests/integration/test_compare_integration.py`:

```python
from pathlib import Path

import pytest

pytest.importorskip("docling")
pytest.importorskip("markitdown")

from docsift.services.comparison_service import compare_document  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"

pytestmark = pytest.mark.integration


def test_compare_table_pdf_with_real_engines(tmp_path):
    comparison = compare_document(FIXTURES / "table.pdf", output_dir=tmp_path)
    by_engine = {run.engine: run for run in comparison.runs}
    assert by_engine["docling"].success is True
    assert by_engine["markitdown"].success is True
    assert by_engine["docling"].table_count >= 1
    assert (tmp_path / "table.compare.json").exists()
    assert (tmp_path / "table.compare.md").exists()
```

- [ ] **Step 4: Run the integration test**

Run: `uv run pytest tests/integration -m integration -v`
Expected: all pass, including the new compare test (models are cached; markitdown's pdf extra is installed). If `by_engine["markitdown"].table_count` is 0 that is fine — only docling's is asserted, since pdfminer does not reconstruct tables.

- [ ] **Step 5: Run the full gate and commit**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format .`
Expected: all unit tests pass, integration deselected, ruff clean.

```bash
git add scripts benchmarks tests/fixtures tests/integration/test_compare_integration.py .gitignore
git commit -m "feat: add fixture categories and benchmark corpus manifest"
```

---

### Task 8: Docs and M2 exit verification

**Files:**
- Modify: `README.md`
- Test: manual exit-criteria verification (commands below)

**Interfaces:**
- Consumes: everything above.
- Produces: documented compare workflow; verified M2 exit criteria.

- [ ] **Step 1: Update README**

In `README.md` Usage, after the existing convert lines, add:

```markdown
    uv run docsift compare report.pdf
    uv run docsift compare report.pdf --output ./comparison

`compare` runs every engine on the same document and writes
`<name>.compare.json` (machine-readable metrics) and `<name>.compare.md`
(human-readable report) alongside per-engine output folders.
```

- [ ] **Step 2: Verify M2 exit criteria with real engines**

```bash
uv run docsift compare tests/fixtures/sample.pdf --output /tmp/docsift-m2
uv run docsift compare tests/fixtures/table.pdf --output /tmp/docsift-m2b
```

Expected: exit 0; both engines listed (`docling: ok`, `markitdown: ok`); `sample.compare.json` and `sample.compare.md` exist and the JSON parses (`uv run python -c "import json;json.load(open('/tmp/docsift-m2/sample.compare.json'))"`). Failure capture was proven by unit tests in Tasks 4 and 6.

- [ ] **Step 3: Full gate**

Run: `uv run pytest -v && uv run pytest tests/integration -m integration -v && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document docsift compare workflow"
```

*(Controller pushes and watches CI after the final review, as in M1.)*

---

## Self-review notes

- M2 exit criteria coverage: "same file through both engines" — Tasks 4, 7, 8; "machine-readable comparison JSON" — Tasks 4–5, verified in 8; "failures captured without stopping" — Task 4 (`test_failure_of_one_engine_does_not_stop_comparison`) and Task 6 (partial-failure exit-0 test).
- PRD FR-14 metric list mapped: duration ✓, output characters ✓, estimated tokens ✓, heading count ✓ (Task 2), table count ✓ (Task 2), warnings ✓, OCR usage ✓, success ✓, output file paths ✓. Human quality scoring stays manual per PRD.
- Final-review pre-M2 items included: `schema_version` and registry-derived engine choices (Task 1).
- Type consistency: `EngineRunSummary`/`ComparisonResult` fields used in Tasks 4, 5, 6 match Task 3's definitions; `build_source_metadata` introduced in Task 4 and used only there; `render_report` signature identical in Task 4 (stub) and Task 5 (real).
- Known acceptable stub: Task 4 creates `comparison_report.py` as a one-line renderer that Task 5's failing test replaces — sequenced deliberately so Task 4's artifact test can run.
