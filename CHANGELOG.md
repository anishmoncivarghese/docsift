# Changelog

## 0.5.6 — 2026-08-10

- Listed in the **official MCP Registry**. Adds `server.json` (validated against
  the published `2025-12-11` schema) and the `mcp-name:` ownership marker the
  registry checks against the README published on PyPI — which is why this
  needed a release rather than just a commit.

  The listing installs with `uvx --from "docsift[mcp,docling,markitdown]"
  docsift mcp`, so the extras come along; a bare `uvx docsift` would install the
  CLI without an MCP SDK.

## 0.5.5 — 2026-08-10

Documentation only; no code changes. Released so the page on PyPI matches the
repository, since that is where most people meet the project first.

- **Says which MCP clients this works with, and which it does not.** "MCP
  server" reads to a lot of people as "works with ChatGPT". It does not:
  claude.ai in the browser and ChatGPT both accept only a *remote* server at a
  public HTTPS URL, and DocSift speaks stdio. There is no configuration that
  changes that, so the README now says so before anyone spends 1.6 GB finding
  out. Reaching those clients would mean running DocSift on a server and
  uploading documents to it, which is the opposite of what it is for.

- **Adds the VS Code and Codex CLI configurations**, which were missing —
  including the startup timeout Codex needs. Its default allows ten seconds, and
  DocSift loads PyTorch on the way up, so the default reports a server that
  failed to start when it was only still starting.

## 0.5.4 — 2026-08-10

- **Fixed: two more lines of engine output reached the terminal on Linux.**
  0.5.3 silenced the Python logging, which is all that macOS produces. A first
  run on Linux still showed onnxruntime announcing its PCI bus scan, and — while
  the model cache was still cold — a warning from the HuggingFace Hub about
  unauthenticated requests.

  The Hub one is a logger and simply joins the list. onnxruntime's could not be
  fixed that way: it is C++ writing straight to file descriptor 2, and the
  message is emitted while the module is *importing*, which defeats importing it
  early to lower its log severity. That import now runs with the file descriptor
  detached — only the import, so everything the conversion does afterwards keeps
  a live stderr and real failures still surface.

- Internal: `tests/integration` now runs in CI. It never had, because the normal
  test job installs only the `markitdown` extra — which is how 0.5.2 shipped a
  progress indicator buried under 107 lines of engine logging with every test
  passing. There is also a new `scanned.pdf` fixture of rasterised text, so
  docling's OCR path is exercised; every previous PDF fixture was born-digital
  and skipped it entirely.

## 0.5.3 — 2026-08-10

- **Fixed: the conversion engines' own logging buried everything else.**
  Converting a 34-page PDF wrote 113 lines to stderr, 107 of them from docling
  and its model stack — torch dynamo graph-break notices, and one warning per
  page reporting that OCR found no text, which is the normal case for a
  born-digital PDF rather than a problem.

  It made the progress output added in 0.5.2 effectively invisible, and the wall
  of yellow WARNING lines read like a failure on a conversion that had actually
  succeeded. Same document now writes 7 lines.

  Anything at ERROR or above still comes through. `docsift convert --verbose`,
  or `DOCSIFT_VERBOSE=1` for the MCP server and HTTP API, restores every line —
  which is what a bug report needs.

## 0.5.2 — 2026-08-10

- **`docsift convert` now shows progress instead of going silent.** A cold PDF
  conversion printed nothing for two and a half minutes — on a clean Linux
  machine a three-page, 1.8 KB fixture took 186 seconds, 154 of them with no
  output at all. There was no way to tell a running conversion from a hung one,
  and the reasonable response to that is Ctrl-C.

  The CLI now shows a spinner with the current phase and elapsed time: loading
  the engine, the one-time model download, converting, chunking, writing. It
  writes to stderr, so piping stdout is unaffected; when stderr is not a
  terminal it degrades to one plain line per phase, and `--quiet` turns it off.

  The wait itself is unchanged, and it is worth being clear about where it goes:
  almost all of it is Docling fetching its layout and table models the first
  time it ever runs, plus loading PyTorch. It is startup cost, not page count —
  a three-page file costs about the same as a thirty-page one, and only the
  first conversion pays it.

- **DocSift now says when you are carrying an unused CUDA build of PyTorch.**
  On Linux the default install resolves to the CUDA build: 5.3 GB on disk,
  roughly 2 GB of it `nvidia-*` wheels that a machine without an NVIDIA GPU
  never loads. No published wheel can prevent this — the CPU builds live on a
  separate package index, and package metadata cannot redirect an installer —
  so instead the first conversion on such a machine now reports it, with the
  command that fixes it.

  For uv users, `uv tool install --torch-backend auto` avoids the problem up
  front and brings the install to 1.6 GB, while leaving CUDA in place for people
  who do have a GPU. The README documents it.

- `rich` is now a direct dependency rather than one inherited from `typer`.

## 0.5.1 — 2026-08-09

- **Fixed: the MCP server's default token budget was a third of the CLI's**, so
  `search_document` returned a single chunk per call. Chunks routinely reach
  ~1,000 tokens and the budget was 2,000, which left no room for a second one.
  In practice one question against a 34-page report cost six tool calls, each
  handing back one fragment — spending more tokens in total than the wider
  budget would have. The default is now 5,000, matching `docsift search`, and a
  test holds the two surfaces together.

## 0.5.0 — 2026-08-09

- New `docsift mcp` runs DocSift as a local [MCP](https://modelcontextprotocol.io)
  server over stdio, for Claude Desktop, Claude Code, Codex, Cursor and other MCP
  clients. Install it with the new `mcp` extra.

  Two tools: `search_document` takes a file path and a question and returns only
  the matching passages with page and section metadata, converting the file the
  first time it is seen; `convert_document` converts and indexes a file and
  returns a summary rather than its text. Neither returns a whole document —
  that would put it in the model's context and undo the point.

  The server runs in your own process. Nothing listens on a port and no document
  content crosses the network.

## 0.4.0 — 2026-08-06

Makes DocSift usable from Copilot Studio, Power Automate and n8n.

- New `docsift openapi --format swagger2` emits a **Swagger 2.0** document.
  Power Platform custom connectors do not accept the OpenAPI 3.1 document the
  service serves at `/openapi.json`, so this is what you import.
- New optional API key. Set `DOCSIFT_API_KEY` and every `/v1/*` route requires an
  `X-API-Key` header; `/health`, `/version`, `/openapi.json`, `/docs` and
  `/redoc` stay open. **Off by default** — an existing deployment that sets
  nothing behaves exactly as before. This is a single shared secret, not
  per-user identity.
- Every API operation now carries a summary and a description written for agent
  tool selection, including when to prefer search over retrieving a whole
  document.
- The OpenAPI document declares a `servers` entry, set with
  `DOCSIFT_PUBLIC_URL` (default `http://127.0.0.1:8000`). A connector needs a
  reachable host.
- New `examples/`: an importable n8n workflow that uploads, polls and searches;
  Copilot Studio custom connector instructions; and a Power Automate flow with
  the *Do until* polling loop.

**A Copilot Studio action cannot poll.** Search works as a direct connector call.
Uploading needs a Power Automate flow to wait for conversion — the examples
explain the split rather than pretending one action can wait minutes.

## 0.3.0 — 2026-08-05

Adds local keyword and phrase retrieval (Milestone 5).

- Successful API conversions index normalized chunks in SQLite FTS5. Reprocessing
  the same document replaces its index atomically, and deletion removes its search
  rows together with the document record.
- `GET /v1/documents/{id}/search` returns BM25-ranked chunks with page, section,
  token, score, match, and context metadata. `limit`, `max_tokens`, and `context`
  bound the response so the endpoint never falls back to returning full Markdown.
  `context=N` is a caller-supplied symmetric window of `N` adjacent chunks on
  each side of a direct match (default 0) -- this is the shipped context
  expansion, not the conditional heuristics FR-11 describes; treat FR-11 as not
  yet implemented.
- `docsift search DOCUMENT_ID QUERY` exposes the same retrieval path locally,
  including quoted phrases and context controls.
- Invalid search syntax returns a stable, content-safe error instead of exposing
  SQLite details or echoing the query. Search queries are capped at 1024
  characters and 64 terms, rejected before any query runs; infrastructure faults
  (a missing table, a locked or corrupted database) are no longer misreported as
  invalid queries.
- A document with chunks but no search index -- most commonly one converted
  before this release -- now returns `409` from `/search` instead of a
  200 empty result set indistinguishable from a genuine no-match.
- The FTS5 match is now scoped to the target document via an indexed token,
  instead of resolving across every document's rows before filtering; search
  latency no longer grows with the size of the rest of the corpus.
- The search endpoint's existence check now uses the document metadata row
  instead of parsing the complete stored result, so `/search` is no longer
  more expensive than `/chunks`.
- On a SQLite build without the FTS5 extension, the service still starts and
  every other endpoint still works; only `/search` returns `503`, and
  conversions no longer fail trying to index into a table that doesn't exist.
- Search remains fully local and dependency-free beyond SQLite. It is lexical
  rather than semantic; hybrid retrieval remains planned for a future release
  only if benchmarks justify it.

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
