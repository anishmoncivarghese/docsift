# DocSift

> Convert documents once. Give agents only what they need.

DocSift converts PDFs and Office documents into clean, structured, AI-ready
Markdown and JSON — locally, with no cloud APIs. Docling handles PDFs;
MarkItDown handles the breadth formats; both sit behind one interface.

**v0.4.0**

## Install

DocSift needs at least one conversion engine:

    pip install "docsift[markitdown]"   # Word, Excel, PowerPoint, HTML, CSV, EPUB
    pip install "docsift[docling]"      # PDFs (large download: ML layout models)
    pip install "docsift[all]"          # both

`pip install docsift` alone installs the CLI but no engine, and conversion will
fail with an install hint.

For local development from a clone:

    uv sync --all-extras

## Usage

    docsift convert report.pdf
    docsift convert report.pdf --engine markitdown
    docsift --version
    docsift compare report.pdf
    docsift compare report.pdf --output ./comparison
    docsift inspect report.pdf
    docsift search doc_xxxxxxxxxxxx "operational risk"
    docsift search doc_xxxxxxxxxxxx '"operational risk"' --limit 5 --context 1
    docsift cache info
    docsift cache clear

`compare` runs every engine on the same document and writes
`<name>.compare.json` (machine-readable metrics) and `<name>.compare.md`
(human-readable report) alongside per-engine output folders.

Output defaults to `./output/` and can be changed with `--output DIR`.

## Chunking and cleaning

Conversion cleans the Markdown (repeated headers/footers, page numbers, image
references) and splits it into token-budgeted chunks with heading context:

    docsift convert report.pdf --max-tokens 800 --overlap 100
    docsift convert report.pdf --keep-image-refs
    docsift convert report.pdf --keep-furniture
    docsift convert report.pdf --no-cache

Results are cached in `~/.cache/docsift` (override with `DOCSIFT_CACHE_DIR`);
an unchanged file with unchanged settings returns instantly.

## Search

Search runs fully locally over chunks stored by the HTTP service. It uses SQLite
FTS5 keyword ranking and supports quoted phrases:

    docsift search doc_xxxxxxxxxxxx "operational risk"
    docsift search doc_xxxxxxxxxxxx '"operational risk"' --limit 5
    docsift search doc_xxxxxxxxxxxx "risk" --context 1 --max-tokens 5000

`--limit` controls direct matches (default 5, maximum 20). `--context` includes
up to two adjacent chunks on each side, and `--max-tokens` caps the complete
returned result set. Context chunks are marked separately from direct matches.
The command prints only selected chunks, never the document's complete Markdown.

`score` orders results within a single response only -- it is not comparable
across separate requests or over time. BM25 statistics are corpus-wide, so a
score's magnitude drifts as unrelated documents are indexed or removed.

The search index belongs to `DOCSIFT_DATA_DIR` and is populated by successful
API conversion jobs. `docsift convert`, which writes standalone files to an
output directory, does not add those files to the service's document store.

## HTTP API

    pip install "docsift[all]"   # api extra alone pulls no conversion engine -- see Install
    docsift serve

Then convert a document asynchronously:

    # returns 202 with {"job_id": "...", "document_id": "...", "status": "queued"}
    curl -sS -F file=@report.pdf http://127.0.0.1:8000/v1/documents

    # poll until "succeeded" or "failed"
    curl -sS http://127.0.0.1:8000/v1/jobs/job_xxxxxxxxxxxxxxxx

    # then fetch the result
    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/markdown
    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/chunks

    # keyword search (five direct matches, at most 5,000 returned tokens)
    curl -sS --get \
      --data-urlencode 'q=operational risk' \
      --data 'limit=5' --data 'max_tokens=5000' \
      http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/search

    # exact phrase plus one neighboring chunk on each side
    curl -sS --get \
      --data-urlencode 'q="operational risk"' \
      --data 'context=1' \
      http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/search

Conversion always runs in the background — a long PDF can take minutes, and
clients that assume a synchronous response will time out. The OpenAPI document
is at `/openapi.json`.

State lives in `DOCSIFT_DATA_DIR` (default `~/.local/share/docsift`): a SQLite
database of jobs and documents, plus stored artifacts. Uploads are capped at
50 MB via `DOCSIFT_MAX_UPLOAD_BYTES` (raising it works too, not just lowering
it). `DELETE /v1/documents/{id}` removes the stored document and its database
record, and also purges any cached conversion results for it, so deletion is
genuine rather than leaving a copy recoverable from the cache — including a
document whose conversion is still running when the delete lands: the job is
cancelled and its result is never stored.

Background conversion runs on a pool of `DOCSIFT_JOB_WORKERS` threads
(default 2). Each queued job holds its uploaded original on disk until a
worker reaches it, so the backlog is bounded by `DOCSIFT_MAX_PENDING_JOBS`
(default 32); once it's full, `POST /v1/documents` returns `503` until a slot
frees up.

**Running untrusted documents:** the service converts whatever it is given.
Run it on infrastructure you control and enable the shared API key described
below before making it reachable by other tools.

## Connecting Copilot Studio, Power Automate and n8n

    DOCSIFT_PUBLIC_URL=https://docsift.internal docsift openapi --format swagger2 -o docsift-connector.json

Import that file as a Power Platform custom connector. The service's own
`/openapi.json` is OpenAPI 3.1, which custom connectors do not accept — this
command emits the Swagger 2.0 they need.

A full walkthrough — Python usage, hosting, and step-by-step Copilot Studio and
Power Automate setup — is in [docs/USING_DOCSIFT.md](docs/USING_DOCSIFT.md).

Worked guides live in `examples/`:

- `examples/n8n/` — a workflow you can import directly: upload, poll, search.
- `examples/copilot-studio/` — connector setup and which operations to expose.
- `examples/power-automate/` — the *Do until* flow that waits for conversion.

## Protecting the service

Set `DOCSIFT_API_KEY` and every `/v1/*` route requires an `X-API-Key` header:

    DOCSIFT_API_KEY=your-shared-secret docsift serve
    curl -H "X-API-Key: your-shared-secret" http://127.0.0.1:8000/v1/documents/...

`/health`, `/version`, `/openapi.json`, `/docs` and `/redoc` stay open so
container health checks, connector imports and the interactive API docs keep
working. This is one shared secret for the whole
service — not per-user identity, and no substitute for network controls. If you
set nothing, the service behaves exactly as it did before.

## Docker

> **Not yet build-tested.** The image definition below runs the service as a
> non-root user and is written against the documented behaviour of its base
> images, but no `docker build` has been run against it. Treat it as a starting
> point to verify in your own environment rather than a proven artifact. Running
> DocSift directly (`pip install "docsift[all]"` and `docsift serve`) is the
> path that is exercised by the test suite.

    docker build -t docsift .
    docker run -p 8000:8000 -v docsift-data:/data docsift

That uses a named volume (`docsift-data`) for `/data`, where the SQLite
database and stored documents live.

The image installs **both** engines. Routing sends every PDF to Docling with no
fallback, so an API-only image without it would fail on the format the service
exists for. That makes the image large — Docling's model weights are baked in at
build time rather than downloaded on first use, so the first conversion after a
deploy is not a multi-minute stall and the running container needs no outbound
access to Hugging Face. Torch is pinned to the CPU wheels; the default Linux
build bundles CUDA runtimes that a CPU container will never execute.

Expect a slow first build (model download) and a multi-gigabyte image.

**Use a named volume, not a bare host bind mount.** The container runs as
uid 10001, not root. A named volume like the example above is created
owned by that user automatically. A host bind mount

    docker run -p 8000:8000 -v /host/path:/data docsift   # will not start

arrives **root-owned**, so uid 10001 cannot create the database file and the
container fails on its first request. If you need a bind mount for a
specific host path, `chown 10001:10001 /host/path` first:

    sudo chown 10001:10001 /host/path
    docker run -p 8000:8000 -v /host/path:/data docsift

The image publishes a `HEALTHCHECK` against `/health` and declares `/data`
as a volume.

## Known limitations

- `--overlap` applies to the fallback Markdown chunker only. Docling supplies
  its own chunks for PDFs, and DocSift warns when the option cannot take effect.
- Cleaning removes little from Docling-parsed PDFs, because Docling already
  drops page headers and footers using its layout model. The cleaning stages
  earn their keep on MarkItDown output (Word, HTML, spreadsheets).
- The result cache in `~/.cache/docsift` has no automatic eviction. Use
  `docsift cache info` and `docsift cache clear` to manage it.
- A GFM table written without a leading `|` is not recognised as a table and
  its rows are not protected from de-duplication. This affects hand-written
  Markdown, and table text inside Docling-supplied chunks, which is
  serialized as triplets rather than pipes.
- The `POST /v1/documents` API endpoint rejects an oversized upload before
  buffering it only when the client sends an honest `Content-Length` header.
  A chunked request (no `Content-Length`) or one that understates its size
  is still fully buffered by the framework's multipart parser before the
  size check runs -- the check is still correct, just no longer early, for
  that case.
- The API's optional `DOCSIFT_API_KEY` is a single shared secret. There is no
  per-user identity, no rate limiting and no multi-tenancy — keep the service on
  infrastructure you control.
- A Copilot Studio action cannot poll a long-running conversion. Search works as
  a direct connector call; uploading needs a Power Automate flow with a
  *Do until* loop (see `examples/`).
- Search is lexical SQLite FTS5 retrieval, not semantic search: it does not
  understand synonyms, correct spelling, or match concepts absent from the
  indexed words. Local embeddings and hybrid retrieval remain planned for a
  future release only if benchmarks justify their model and storage cost.
- Search is scoped to one document at a time. Cross-document search is not
  implemented, and per-document search cost still grows somewhat with the
  total number of indexed documents.
- Documents converted before this release are not in the search index;
  `/search` returns `409` for one until it's re-uploaded to index it.
- Search queries are capped at 1024 characters and 64 terms.
- Page-number filtering is not supported, even though pages are returned
  with each search result.
- A `max_tokens` smaller than the first result returns an empty result set.
- Deleted document text can remain in unvacuumed SQLite free pages until the
  database is `VACUUM`ed -- this release is the first to store document text
  inside `docsift.db` (the search index), not just in the filesystem.
- `POST /v1/compare` is not implemented yet.
- Single-process only. Running two instances (or `uvicorn --workers 2`)
  against the same `DOCSIFT_DATA_DIR` makes each instance's startup mark the
  *other* instance's live jobs as `failed`/`interrupted`, since each assumes
  any `queued`/`processing` row it didn't create was abandoned by a crashed
  process.
- Conversions run with no processing timeout. A pathological document can
  occupy a worker indefinitely; with the default of 2 workers, two such
  documents wedge the service.
- `.zip` uploads are expanded by MarkItDown without a decompression-ratio or
  member-count bound.
- Document ids are derived from file content (a content hash), not issued as
  capability tokens. Two callers who upload the same bytes share one
  document, and either can retrieve or delete it.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOCSIFT_DATA_DIR` | `~/.local/share/docsift` | SQLite database and stored documents. |
| `DOCSIFT_CACHE_DIR` | `~/.cache/docsift` | Disposable conversion-result cache. |
| `DOCSIFT_MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Upload size ceiling; can be raised or lowered. |
| `DOCSIFT_JOB_WORKERS` | `2` | Background conversion threads. |
| `DOCSIFT_MAX_PENDING_JOBS` | `32` | Queued + in-flight job ceiling; `POST /v1/documents` returns `503` past it. |
| `DOCSIFT_API_KEY` | unset | Optional shared secret required as `X-API-Key` on `/v1/*` routes. |
| `DOCSIFT_PUBLIC_URL` | `http://127.0.0.1:8000` | Reachable base URL advertised in OpenAPI and Swagger connector documents. |

## Privacy, security and contributing

DocSift is software you run, not a service. It has no telemetry and never
transmits document content anywhere — [PRIVACY.md](PRIVACY.md) covers what it
writes to disk, when it touches the network, and what changes if you host it for
other people.

To report a vulnerability, or to understand what the service does and does not
defend against, see [SECURITY.md](SECURITY.md). To work on DocSift, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
