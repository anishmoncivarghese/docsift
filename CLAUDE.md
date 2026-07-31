# DocSift

Open-source document-preparation gateway: PDFs and Office files in → clean, structured, AI-ready Markdown/JSON + token-aware chunks out. Local-first, no paid APIs for core conversion.

**Tagline:** Convert documents once. Give agents only what they need.

## Key documents (read before making product decisions)

- **PRD (source of truth for scope):** `../DocSift_PRD_v0.2.md`
- **v0.1 spec:** `docs/specs/v0.1-spec.md`
- **Active plan:** `docs/superpowers/plans/2026-08-01-m0-m1-bootstrap-and-conversion.md`

The product owner is a non-technical founder: explain trade-offs in plain language, keep responses concise, and never assume knowledge of programming jargon.

## Commands

```bash
uv sync --all-extras            # install with both engines (docling is large)
uv sync --extra markitdown      # lighter install (what CI uses)
uv run pytest                   # unit tests (integration excluded by default)
uv run pytest -m integration    # real-engine tests (docling downloads models on first run)
uv run ruff check . && uv run ruff format --check .
uv run docsift --help
```

## Architecture (src layout, package `docsift`)

- `core/` — Pydantic models (the engine-neutral schema), exceptions. No engine knowledge.
- `engines/` — `base.py` (ConversionEngine ABC), `registry.py` (lazy loading), `router.py` (file type → engine), one adapter module per engine.
- `processing/` — token_estimator; cleaner + chunker arrive in Milestone 3.
- `services/` — `conversion_service.py` orchestrates validate → route → convert → normalize → write.
- `cli/` — Typer app; entry point `docsift`.

## Hard rules

1. **Engine imports stay lazy** (inside methods). `docsift --help` must work with neither engine installed. Never import `docling` or `markitdown` at module top level.
2. **Docling and MarkItDown are dependencies, never vendored or forked** (PRD §14). Pin via `uv.lock`.
3. **All PDFs route to Docling** in auto mode. MarkItDown gets PDFs only via explicit `--engine markitdown` or compare mode. No PDF complexity detection — it is a PRD non-goal.
4. **No engine-specific types outside `engines/`.** Everything downstream consumes `core.models` only.
5. **Never log or print document contents** — not in logs, not in error messages, not in CLI output. Filenames and metrics are fine.
6. **uv only.** No pip install, no poetry, no requirements.txt.
7. **TDD:** failing test first, minimal implementation, then commit. Integration tests (real engine runs) are marked `@pytest.mark.integration` and excluded by default.
8. **Conventional commits:** `feat:`, `fix:`, `test:`, `chore:`, `ci:`, `docs:`.

## Definition of done for any change (PRD §22)

Implemented + tested + existing tests pass + ruff clean + type hints on public functions + user-facing behavior documented + no document contents or secrets logged + dependency changes justified.
