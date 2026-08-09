# Convert Progress Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 150-second silent gap during PDF conversion with a live spinner that names the current phase, ticks elapsed seconds, and explains the one-time model download.

**Architecture:** A tiny progress protocol in `core/progress.py` (event + callback + exception-swallowing `emit` helper) is threaded as an optional `on_progress` keyword from `convert_document` down into the engines. The CLI supplies a rich-based renderer that writes to stderr; every other caller passes nothing and behaves exactly as it does today.

**Tech Stack:** Python 3.11+, typer, rich, pydantic, pytest.

## Global Constraints

- Progress output goes to **stderr only**. stdout stays clean for piping.
- `on_progress` defaults to `None` everywhere. MCP server, HTTP API and `ingest_service` are not modified.
- A callback that raises must never fail a conversion.
- **No test may import docling.** CI installs only the `markitdown` extra. All docling behavior is tested through fakes.
- No progress message may contain document content — phases and the user-supplied filename only.
- Existing lazy-import discipline holds: heavy imports stay inside functions (see `tests/unit/test_lazy_imports.py`).

---

### Task 1: Progress protocol

**Files:**
- Create: `src/docsift/core/progress.py`
- Test: `tests/unit/test_progress.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ProgressEvent(phase: str, message: str)`, `ProgressCallback = Callable[[ProgressEvent], None]`, `emit(callback: ProgressCallback | None, phase: str, message: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_progress.py
import pytest

from docsift.core.progress import ProgressEvent, emit


def test_emit_calls_the_callback_with_an_event():
    seen = []
    emit(seen.append, "convert", "converting report.pdf")
    assert seen == [ProgressEvent(phase="convert", message="converting report.pdf")]


def test_emit_is_a_no_op_when_callback_is_none():
    emit(None, "convert", "converting report.pdf")


def test_emit_swallows_callback_exceptions():
    def explode(event):
        raise RuntimeError("renderer is broken")

    emit(explode, "convert", "converting report.pdf")


def test_progress_event_is_frozen():
    event = ProgressEvent(phase="convert", message="x")
    with pytest.raises(Exception):
        event.phase = "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_progress.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docsift.core.progress'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/docsift/core/progress.py
"""Progress reporting for long conversions.

A cold PDF conversion spends minutes inside one opaque engine call. These
events let a front end say what is happening; every consumer is optional and
a front end that breaks must never break a conversion.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressEvent:
    """One phase transition during a conversion."""

    phase: str
    """Machine-readable key, e.g. 'engine_load'. Stable; front ends may match on it."""

    message: str
    """Human-readable text for display."""


ProgressCallback = Callable[[ProgressEvent], None]


def emit(callback: ProgressCallback | None, phase: str, message: str) -> None:
    """Report a phase. Never raises: a broken renderer must not fail a conversion."""
    if callback is None:
        return
    try:
        callback(ProgressEvent(phase=phase, message=message))
    except Exception:  # noqa: BLE001 - progress is decoration, never a failure mode
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_progress.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/docsift/core/progress.py tests/unit/test_progress.py
git commit -m "feat: add a progress event protocol for long conversions"
```

---

### Task 2: Accept `on_progress` in the engine interface

Adding the keyword to the abstract interface first means Task 3 can thread it
without touching two layers at once. The two in-repo test doubles must accept
it too, or `convert_document` will raise `TypeError` when it passes the keyword.

**Files:**
- Modify: `src/docsift/engines/base.py:26-28`
- Modify: `src/docsift/engines/markitdown_engine.py:25`
- Modify: `src/docsift/engines/docling_engine.py:33`
- Modify: `tests/unit/test_registry.py:11-20` (FakeEngine)
- Modify: `tests/unit/test_api_documents.py:15` (OkEngine) and `:270` (FailingEngine)
- Test: `tests/unit/test_markitdown_engine.py`

**Interfaces:**
- Consumes: `ProgressCallback`, `emit` from Task 1.
- Produces: `ConversionEngine.convert(self, path, options=None, on_progress=None) -> EngineOutput`. `MarkItDownEngine` emits phases `engine_load` then `convert`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_markitdown_engine.py
def test_markitdown_reports_progress_phases(tmp_path):
    from docsift.engines.markitdown_engine import MarkItDownEngine

    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    seen = []
    MarkItDownEngine().convert(source, on_progress=seen.append)

    assert [event.phase for event in seen] == ["engine_load", "convert"]
    assert "note.csv" in seen[-1].message


def test_markitdown_converts_without_a_callback(tmp_path):
    from docsift.engines.markitdown_engine import MarkItDownEngine

    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    assert MarkItDownEngine().convert(source).markdown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_markitdown_engine.py -v`
Expected: FAIL with `TypeError: convert() got an unexpected keyword argument 'on_progress'`

- [ ] **Step 3: Write minimal implementation**

In `src/docsift/engines/base.py`, replace the abstract `convert` and add the import:

```python
from docsift.core.progress import ProgressCallback
```

```python
    @abstractmethod
    def convert(
        self,
        path: Path,
        options: ConversionOptions | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> EngineOutput:
        """Convert the file at `path`. Raises on failure; never returns None.

        `on_progress` is optional and advisory: implementations report phases
        through `docsift.core.progress.emit`, which ignores a None callback.
        """
```

In `src/docsift/engines/markitdown_engine.py`, change the signature and wrap the import:

```python
    def convert(
        self,
        path: Path,
        options: ConversionOptions | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> EngineOutput:
        emit(on_progress, "engine_load", "loading markitdown")
        from markitdown import MarkItDown

        emit(on_progress, "convert", f"converting {path.name}")
        try:
            result = MarkItDown().convert(str(path))
```

with `from docsift.core.progress import ProgressCallback, emit` at module top.

In `src/docsift/engines/docling_engine.py`, widen the signature only (phases land in Task 4):

```python
    def convert(
        self,
        path: Path,
        options: ConversionOptions | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> EngineOutput:
```

with `from docsift.core.progress import ProgressCallback, emit` at module top.

In `tests/unit/test_registry.py`, `tests/unit/test_api_documents.py`, widen each
double's signature the same way, e.g.:

```python
    def convert(self, path, options=None, on_progress=None):
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit -v`
Expected: PASS, no regressions

- [ ] **Step 5: Commit**

```bash
git add src/docsift/engines tests/unit
git commit -m "feat: let conversion engines report progress phases"
```

---

### Task 3: Thread `on_progress` through `convert_document`

**Files:**
- Modify: `src/docsift/services/conversion_service.py:94-101` (signature), `:107` (cache check), `:126` (engine call), `:148` (chunking), `:213` (write)
- Test: `tests/unit/test_conversion_service.py`

**Interfaces:**
- Consumes: `emit` from Task 1, the widened engine signature from Task 2.
- Produces: `convert_document(path, engine="auto", output_dir=None, options=None, use_cache=True, on_progress=None) -> ConversionResult`. Phase order on a cold run: `cache_check`, then whatever the engine emits, then `chunk`, then `write`. A cache hit emits `cache_check` and `write` only.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_conversion_service.py
def test_convert_document_reports_phases(tmp_path):
    from docsift.services.conversion_service import convert_document

    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    seen = []
    convert_document(
        source, output_dir=tmp_path / "out", use_cache=False, on_progress=seen.append
    )
    phases = [event.phase for event in seen]

    assert phases[0] == "cache_check"
    assert "chunk" in phases
    assert phases[-1] == "write"


def test_convert_document_survives_a_broken_callback(tmp_path):
    from docsift.services.conversion_service import convert_document

    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    def explode(event):
        raise RuntimeError("renderer is broken")

    result = convert_document(
        source, output_dir=tmp_path / "out", use_cache=False, on_progress=explode
    )
    assert result.document_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_conversion_service.py -k progress -v`
Expected: FAIL with `TypeError: convert_document() got an unexpected keyword argument 'on_progress'`

- [ ] **Step 3: Write minimal implementation**

Add `from docsift.core.progress import ProgressCallback, emit` to the imports, then:

```python
def convert_document(
    path: Path,
    engine: str = "auto",
    output_dir: Path | None = None,
    options: ConversionOptions | None = None,
    use_cache: bool = True,
    on_progress: ProgressCallback | None = None,
) -> ConversionResult:
```

Emit `cache_check` immediately before `if use_cache:`:

```python
    emit(on_progress, "cache_check", "checking cache")
```

In the cache-hit branch, before `_write_artifacts(cached, path, output_dir)`:

```python
            emit(on_progress, "write", "writing output")
```

Pass the callback to the engine:

```python
        output = engine_impl.convert(path, options, on_progress=on_progress)
```

Before the `if output.chunks is not None:` block:

```python
    emit(on_progress, "chunk", "chunking")
```

Before the final `_write_artifacts(result, path, output_dir)`:

```python
    emit(on_progress, "write", "writing output")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_conversion_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/docsift/services/conversion_service.py tests/unit/test_conversion_service.py
git commit -m "feat: report conversion phases from convert_document"
```

---

### Task 4: First-run detection and docling phases

**Files:**
- Modify: `src/docsift/engines/docling_engine.py`
- Test: `tests/unit/test_docling_engine_unit.py`

**Interfaces:**
- Consumes: `emit` from Task 1.
- Produces: `models_are_cached() -> bool` at module level in `docling_engine.py`. `DoclingEngine.convert` emits `engine_load`, optionally `model_download`, then `convert`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_docling_engine_unit.py
import os
from pathlib import Path


def test_models_are_cached_is_false_when_caches_are_empty(tmp_path, monkeypatch):
    from docsift.engines.docling_engine import models_are_cached

    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert models_are_cached() is False


def test_models_are_cached_is_true_when_the_hub_cache_has_content(tmp_path, monkeypatch):
    from docsift.engines.docling_engine import models_are_cached

    hub = tmp_path / "hf" / "hub" / "models--ds4sd--docling-models"
    hub.mkdir(parents=True)
    (hub / "config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert models_are_cached() is True


def test_models_are_cached_is_true_when_docling_cache_has_content(tmp_path, monkeypatch):
    from docsift.engines.docling_engine import models_are_cached

    monkeypatch.delenv("HF_HOME", raising=False)
    home = tmp_path / "home"
    docling_cache = home / ".cache" / "docling" / "models"
    docling_cache.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert models_are_cached() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_docling_engine_unit.py -k models_are_cached -v`
Expected: FAIL with `ImportError: cannot import name 'models_are_cached'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/docsift/engines/docling_engine.py` (module level, after the imports;
add `import os` at the top):

```python
def models_are_cached() -> bool:
    """True when docling's models look present on disk.

    Filesystem-only on purpose: it must answer before docling is imported, and
    must work in a test run where docling is not installed at all. When the
    answer is uncertain -- an unreadable home directory, say -- it returns True
    so the caller stays quiet. A false "downloading 1 GB" on every warm run
    would be a worse defect than the silence this is helping to fix.
    """
    hf_home = os.environ.get("HF_HOME")
    hub = Path(hf_home) / "hub" if hf_home else Path.home() / ".cache" / "huggingface" / "hub"
    candidates = (hub, Path.home() / ".cache" / "docling")
    for candidate in candidates:
        try:
            if candidate.is_dir() and any(candidate.iterdir()):
                return True
        except OSError:
            return True  # cannot tell; stay quiet
    return False
```

Then in `DoclingEngine.convert`, replace the body's opening:

```python
        emit(on_progress, "engine_load", "loading docling (this imports PyTorch)")
        if not models_are_cached():
            emit(
                on_progress,
                "model_download",
                "first run: downloading layout and table models (~1 GB). "
                "This happens once.",
            )
        from docling.document_converter import DocumentConverter

        chunk_options = options.chunk if options else ChunkOptions()
        emit(on_progress, "convert", f"converting {path.name}")
        try:
            result = DocumentConverter().convert(str(path))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_docling_engine_unit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/docsift/engines/docling_engine.py tests/unit/test_docling_engine_unit.py
git commit -m "feat: warn once about the first-run model download"
```

---

### Task 5: CLI renderer and `--quiet`

**Files:**
- Create: `src/docsift/cli/progress.py`
- Modify: `src/docsift/cli/main.py:34-73` (convert command)
- Modify: `pyproject.toml:9-13` (dependencies)
- Test: `tests/unit/test_cli_progress.py`

**Interfaces:**
- Consumes: `ProgressEvent`, `ProgressCallback` from Task 1; `convert_document(..., on_progress=)` from Task 3.
- Produces: `progress_reporter(enabled: bool = True) -> ContextManager[ProgressCallback | None]` in `docsift.cli.progress`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cli_progress.py
from typer.testing import CliRunner

from docsift.cli.main import app
from docsift.cli.progress import progress_reporter
from docsift.core.progress import ProgressEvent

runner = CliRunner()


def test_non_tty_reporter_writes_plain_lines_to_stderr(capsys):
    with progress_reporter(enabled=True) as report:
        report(ProgressEvent(phase="convert", message="converting note.csv"))
    captured = capsys.readouterr()
    assert "converting note.csv" in captured.err
    assert "\x1b[" not in captured.err
    assert captured.out == ""


def test_disabled_reporter_yields_none_and_prints_nothing(capsys):
    with progress_reporter(enabled=False) as report:
        assert report is None
    assert capsys.readouterr().err == ""


def test_sticky_phase_is_printed_and_not_only_spun(capsys):
    with progress_reporter(enabled=True) as report:
        report(
            ProgressEvent(
                phase="model_download",
                message="first run: downloading layout and table models (~1 GB).",
            )
        )
        report(ProgressEvent(phase="convert", message="converting note.csv"))
    assert "downloading layout and table models" in capsys.readouterr().err


def test_convert_still_succeeds_with_progress_enabled(tmp_path):
    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["convert", str(source), "--output", str(tmp_path / "out"), "--no-cache"],
    )
    assert result.exit_code == 0, result.output
    assert "document_id:" in result.output


def test_quiet_runs_clean(tmp_path):
    source = tmp_path / "note.csv"
    source.write_text("name,role\nada,engineer\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["convert", str(source), "--output", str(tmp_path / "out"), "--quiet", "--no-cache"],
    )
    assert result.exit_code == 0, result.output
    assert "checking cache" not in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli_progress.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'docsift.cli.progress'`

- [ ] **Step 3: Write minimal implementation**

Create `src/docsift/cli/progress.py`:

```python
"""Terminal rendering for conversion progress.

Writes to stderr so `docsift convert x.pdf > out.txt` stays machine-readable,
and degrades to plain lines when stderr is not a terminal so CI logs stay
readable.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from docsift.core.progress import ProgressCallback, ProgressEvent

# Phases whose message must survive the rest of the run instead of being
# overwritten by the next spinner update.
STICKY_PHASES = frozenset({"model_download"})


@contextmanager
def progress_reporter(enabled: bool = True) -> Iterator[ProgressCallback | None]:
    """Yield a progress callback, or None when progress is switched off."""
    if not enabled:
        yield None
        return

    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    console = Console(stderr=True)

    if not console.is_terminal:
        def plain(event: ProgressEvent) -> None:
            console.print(event.message, highlight=False, markup=False)

        yield plain
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        # total=None keeps the bar indeterminate: docling exposes no page
        # callback, and a fake percentage would be worse than none.
        task_id = progress.add_task("starting", total=None)

        def update(event: ProgressEvent) -> None:
            if event.phase in STICKY_PHASES:
                progress.console.print(event.message, highlight=False, markup=False)
            progress.update(task_id, description=event.message)

        yield update
```

In `src/docsift/cli/main.py`, add the option to `convert` after `no_cache`:

```python
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress progress output on stderr."
    ),
```

and replace the `try:` block that calls `convert_document`:

```python
    from docsift.cli.progress import progress_reporter

    try:
        with progress_reporter(enabled=not quiet) as on_progress:
            result = convert_document(
                path,
                engine=engine,
                output_dir=output,
                options=options,
                use_cache=not no_cache,
                on_progress=on_progress,
            )
    except DocSiftError as exc:
```

In `pyproject.toml`, add `rich` to `dependencies` (it currently arrives only
transitively through typer, which is not a contract):

```toml
dependencies = [
  "typer>=0.12",
  "rich>=13",
  "pydantic>=2.7",
  "tiktoken>=0.8",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit -v && uv run ruff check . && uv run ruff format --check .`
Expected: PASS, no regressions

- [ ] **Step 5: Commit**

```bash
git add src/docsift/cli tests/unit/test_cli_progress.py pyproject.toml uv.lock
git commit -m "feat: show a live spinner while a conversion runs"
```

---

### Task 6: README corrections

Three separate defects, one commit — they are all "what a stranger is told
before they install".

**Files:**
- Modify: `README.md` (quickstart install block, the "what to expect" table, the cold-start paragraph in step 3, the search caveat near line 183)

**Interfaces:**
- Consumes: nothing. Documentation only.
- Produces: nothing.

- [ ] **Step 1: Reframe cold start as fixed cost**

The current text ties the wait to page count: *"a 34-page report takes about
three minutes while the layout and table models run"*. Replace it, and the
matching row of the "what to expect" table, with the measured behavior:

> The first PDF you convert takes about three minutes — and it is startup
> cost, not page count. Docling downloads its layout and table models from
> HuggingFace on that first conversion, then loads PyTorch. A three-page test
> file takes as long as a thirty-page report. Every conversion after that is
> fast, and a file you have already converted answers immediately even if you
> move or rename it.

Keep the existing measured numbers elsewhere in the table intact.

- [ ] **Step 2: Document the Linux install size**

After the `uv tool install` command in step 1, add:

> **On Linux, add `--torch-backend cpu`.** The default install pulls the CUDA
> build of PyTorch — 5.3 GB on disk, including roughly 2 GB of `nvidia-*`
> wheels a machine without an NVIDIA GPU never loads. With the flag it is
> 1.6 GB and conversion is unchanged:
>
>     uv tool install --python 3.12 --torch-backend cpu "docsift[mcp,docling,markitdown]"
>
> macOS wheels are CPU-only already, so the flag changes nothing there.

- [ ] **Step 3: State plainly that search is lexical**

Expand the existing caveat near line 183 into something a reader cannot miss:

> **Search is lexical, not semantic.** DocSift indexes chunks in SQLite FTS5
> and ranks them with BM25. It matches the words you type — not synonyms, not
> paraphrases. Ask for "termination clause" and a section that only ever says
> "ending the agreement" will not come back.
>
> That is a deliberate trade: no embedding model to download, no index to
> rebuild, no GPU, and nothing leaves your machine. If you need semantic
> retrieval, DocSift's Markdown and chunk JSON are a clean input to a vector
> store — that is a reasonable thing to want, and it is not what this tool
> does today.

- [ ] **Step 4: Verify the claims still hold**

Run: `grep -n "34-page\|three minutes\|lexical\|torch-backend" README.md`
Expected: no surviving sentence attributes the cold-start wait to page count;
the CPU flag appears in the install section; the lexical caveat is present.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: correct cold start, Linux install size, and the search caveat"
```

---

## Verification before merge

- [ ] `uv run pytest -v` — all tests pass
- [ ] `uv run ruff check . && uv run ruff format --check .` — clean
- [ ] Manual: `docsift convert tests/fixtures/multipage.pdf` in a terminal shows a ticking spinner (requires the docling extra; not available in CI)
- [ ] Manual: `docsift convert tests/fixtures/sample.pdf --quiet 2>/dev/null` still prints its result block on stdout
- [ ] The `cleanroom.yml` workflow is deleted or kept deliberately, not left by accident
