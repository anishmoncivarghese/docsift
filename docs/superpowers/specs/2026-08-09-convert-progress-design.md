# Progress reporting for `docsift convert`

**Date:** 2026-08-09
**Status:** approved

## Problem

Converting a PDF prints nothing for two and a half minutes.

A clean-room run on a fresh Linux machine (GitHub Actions, workflow
`cleanroom.yml`, run 31323700416) converted `tests/fixtures/multipage.pdf` — 1.8 KB,
3 pages, 54 tokens of output — in **186 seconds**. The logs show a dead gap from
`16:26:46` to `16:29:20`: 154 seconds during which the process writes nothing at
all before the result appears.

Two conclusions follow.

**The wait is fixed cost, not per-page cost.** The README currently says "a
34-page report takes about three minutes while the layout and table models run",
which reads as though page count drives the wait. It does not. Someone who picks
a two-page PDF to try the tool quickly waits just as long.

**Silence is the actual defect.** A first-time user has no way to distinguish a
running conversion from a hung process, and the natural response at ninety
seconds is Ctrl-C. This is the most likely negative first impression when the
project is posted publicly, and no amount of documentation fixes it.

The time is spent inside two opaque steps in `DoclingEngine.convert`: the
`from docling.document_converter import DocumentConverter` statement, which pulls
in PyTorch, and the `DocumentConverter().convert(path)` call, which downloads
layout and table models from the HuggingFace hub on first run and then runs them.

## Goals

- No silent gap longer than a couple of seconds during a CLI conversion.
- The user learns *why* the first run is slow, and that it happens only once.
- Nothing changes for the MCP server, the HTTP API, or piped/scripted use.

## Non-goals

- Making conversion faster. That is a separate question, possibly answered by
  pre-warming models at install time.
- Per-page or percentage progress. Docling exposes no stable callback for it,
  and an honest spinner beats a fake percentage.

## Design

### 1. Progress protocol — `src/docsift/core/progress.py`

```python
@dataclass(frozen=True)
class ProgressEvent:
    phase: str      # machine-readable key, e.g. "engine_load"
    message: str    # human-readable text for display

ProgressCallback = Callable[[ProgressEvent], None]
```

Plus an `emit(callback, phase, message)` helper that does nothing when the
callback is `None` and **swallows any exception the callback raises**. A broken
progress renderer must never fail a conversion.

### 2. Threading the callback

`convert_document()` and `ConversionEngine.convert()` gain an optional
`on_progress: ProgressCallback | None = None`. The default of `None` means
existing callers — `mcp_server.py`, `api/app.py`, `ingest_service.py` — behave
exactly as they do today with no changes.

Phase sequence emitted by `convert_document`:

| Phase | Message | Emitted when |
|---|---|---|
| `cache_check` | `checking cache` | before `load_cached` |
| `engine_load` | `loading docling (this imports PyTorch)` | engine, before its slow import |
| `model_download` | `first run: downloading layout and table models (~1 GB). This happens once.` | engine, only when the cache is cold |
| `convert` | `converting <filename>` | engine, before the converter call |
| `chunk` | `chunking` | before chunking |
| `write` | `writing output` | before `_write_artifacts` |

`engine_load`, `model_download` and `convert` are emitted by the engines, since
only they know when their imports happen. `MarkItDownEngine` emits `engine_load`
and `convert` and never `model_download`.

A cache hit short-circuits after `cache_check`, so a warm run shows almost
nothing — which is correct, because a warm run is fast.

### 3. First-run detection — `models_are_cached()`

Best-effort **filesystem** check — it must not import docling, so it stays
usable and testable on a machine without the docling extra. It looks for a
non-empty HuggingFace hub cache (`HF_HOME` if set, else `~/.cache/huggingface/hub`)
and docling's own cache directory (`~/.cache/docling`). The clean-room logs
confirm the models arrive over the HF hub on first convert, so the hub cache is
the reliable signal.

The rule when detection is uncertain is **stay quiet**. A false "downloading
1 GB" on every warm run is a worse defect than the silence being fixed. The
message appears only when the function positively determines the cache is
missing or empty.

### 4. CLI renderer — `src/docsift/cli/progress.py`

Uses `rich`, which becomes an explicit dependency (`rich>=13`). It currently
arrives only transitively through `typer`, which is not something to rely on.

- **Output goes to stderr**, never stdout, so `docsift convert x.pdf > out.txt`
  stays clean and machine-readable.
- **TTY:** a `rich.progress.Progress` with `SpinnerColumn`, a description column
  and `TimeElapsedColumn`. The elapsed timer ticking is the part that answers
  "is this hung?" — the description alone would sit static for 150 seconds.
- **Not a TTY:** one plain line per phase, no ANSI, no spinner, so CI logs and
  redirected output stay readable.
- **`--quiet` flag** on `docsift convert` suppresses it entirely.
- Context-managed, so an exception mid-conversion stops the spinner and leaves
  the terminal in a clean state before the error is printed.

### 5. Error handling

- A callback that raises is caught and ignored inside `emit`; conversion
  continues.
- The renderer's context manager exits on exception, so `DocSiftError` handling
  in the CLI prints its message normally.
- No progress event carries document content — only phases and the filename the
  user already typed.

## Testing

- Fake engine plus a recording callback: assert the exact phase sequence for a
  cold conversion and for a cache hit.
- A callback that raises `RuntimeError` does not fail the conversion.
- Non-TTY renderer produces plain lines and no ANSI escapes.
- `models_are_cached()` with a monkeypatched cache directory, both cold and warm.
- `--quiet` produces no stderr output.

CI installs only the `markitdown` extra, so **no test may import docling**. All
docling-specific behavior is tested through a fake engine.

## README changes

Shipped as a separate commit from the code.

1. **Reframe cold start.** Replace the page-count framing with the measured
   fact: roughly 2.5–3 minutes of fixed startup on the first PDF regardless of
   size (3-page fixture: 186s on clean Linux), near-instant after that. State
   that models download from HuggingFace on first *convert*, not at install.

2. **Linux install size.** The default `uv tool install` pulls the CUDA build of
   PyTorch on Linux: 5.3 GB installed, including ~1.9 GB of `nvidia-*` wheels
   and 189 MB of `triton` that a CPU-only machine never uses. Document
   `--torch-backend cpu`, measured at **1.6 GB** with docling still working
   (run 31324026751). The `cpu-torch` dependency group in `pyproject.toml` fixes
   this for the Dockerfile only; groups are not published in the wheel, so
   users installing from PyPI do not get it.

3. **Say the search is lexical.** SQLite FTS5 with BM25 ranking, not embeddings:
   exact word matching, no synonyms, no semantic similarity. State the reason —
   no model to download, no index to build, no GPU — so the tradeoff reads as a
   choice rather than an omission.

## Out of scope, worth tracking

- Pre-warming models during install to remove the first-run download from the
  first conversion.
- An `--offline` or explicit `docsift warm` command.
- Whether the 5.3 GB default install should be fixed in packaging rather than
  documentation.
