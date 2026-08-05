# Changelog

## 0.2.0 — 2026-08-05

Adds an HTTP API.

- `docsift serve` runs a FastAPI service (install with `pip install "docsift[api]"`).
- `POST /v1/documents` accepts an upload and returns `202` with a job id and a
  document id immediately; conversion runs in the background. Clients poll
  `GET /v1/jobs/{job_id}` until the status is `succeeded` or `failed`. The API is
  asynchronous by design: Docling on a long PDF routinely exceeds the ~120-second
  timeout that Power Platform custom connectors enforce.
- `GET /v1/documents/{id}`, `/markdown` and `/chunks` retrieve the result;
  `DELETE /v1/documents/{id}` removes it and its stored files.
- Job and document metadata live in SQLite under `DOCSIFT_DATA_DIR`
  (default `~/.local/share/docsift`), separate from the disposable conversion
  cache in `DOCSIFT_CACHE_DIR`.
- Jobs left `queued` or `processing` by a stopped process are reported as
  `failed` with error `interrupted` on the next startup rather than hanging.
- Uploads are capped at 50 MB (`DOCSIFT_MAX_UPLOAD_BYTES`, adjustable in either
  direction), unsupported types are rejected with `415`, and the client's
  filename is never used as a path.
- `DELETE /v1/documents/{id}` cancels a conversion still in progress instead
  of letting the worker resurrect it afterwards; returns `202` when nothing
  existed yet but a job was cancelled, `204` for a normal completed delete.
- The `engine` form field is validated against the registered engines before
  an upload is accepted; an unrecognized value is rejected with `400` rather
  than stored verbatim in the job's error text.
- The background job backlog is bounded (`DOCSIFT_MAX_PENDING_JOBS`, default
  32); `POST /v1/documents` returns `503` once it's full instead of queuing
  uploads without limit.
- Installing `docsift[all]` now also pulls the `api` extra
  (fastapi/uvicorn/python-multipart), so it's a complete install for both
  conversion engines and the HTTP API.
- The conversion cache key includes the DocSift version, so this 0.2.0 bump
  invalidates every cache entry written by 0.1.x — the first conversion after
  upgrading always re-runs rather than returning a stale cached result.
- A `Dockerfile` runs the service as a non-root user, pins its `uv` base
  image, declares `/data` as a volume, and adds a `HEALTHCHECK`.
- OpenAPI at `/openapi.json`, with stable operation ids for connector imports.

Search (`/v1/documents/{id}/search`) and `POST /v1/compare` are not implemented yet.

## 0.1.1 — 2026-08-03

Closes the limitations documented in 0.1.0.

- Cleaning decisions now apply to engine-supplied chunks, so chunk text from
  Docling-parsed PDFs no longer keeps the headers, footers and page numbers
  stripped from the Markdown. Chunks left empty by cleaning are dropped and
  token counts are recomputed.
- `--overlap` now emits a warning when the engine supplies its own chunks and
  the option cannot take effect, instead of being silently ignored.
- The chunker treats fenced code blocks as atomic: a `#` comment inside a code
  sample is no longer parsed as a heading, a pipe-containing line is no longer
  parsed as a table row, and a fence is never split across chunks.
- First-page content is attributed to page 1 instead of page 2.
- New `docsift inspect` shows routing, identity and cache status for a file
  without converting it.
- New `docsift cache info` and `docsift cache clear` for managing the result
  cache.
- Converting two same-named files from different directories into one output
  directory now warns instead of silently replacing the earlier result.

## 0.1.0 — 2026-08-01

First release.

- Convert PDFs (Docling) and Office/HTML/CSV/EPUB files (MarkItDown) to clean
  Markdown plus a normalized JSON result — fully local, no cloud APIs.
- Cleaning: repeated header/footer removal, page-number removal, image-reference
  stripping, page markers as HTML comments.
- Chunking: heading-aware, token-budgeted (tiktoken o200k_base), tables kept
  intact; Docling documents use Docling's HybridChunker.
- Token estimates for raw output, cleaned Markdown, and every chunk.
- Result caching keyed on file hash, engine version, DocSift version, and options.
- `docsift compare`: run both engines on one document with a metrics report.
- CLI: `docsift convert` / `docsift compare` / `--engine` / `--max-tokens` /
  `--overlap` / `--no-cache` / `--output` / `--keep-image-refs` /
  `--keep-furniture`.

### Known limitations

- PDF chunks come from Docling's HybridChunker and are built from the raw
  document, so cleaning (header/footer removal, page-number stripping)
  applies to the exported Markdown but not to chunk text on that path.
- `--overlap` has no effect on PDFs chunked by Docling; it applies only to
  the fallback Markdown chunker.
- The result cache in `~/.cache/docsift` has no automatic eviction.
