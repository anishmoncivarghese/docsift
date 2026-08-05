# DocSift

> Convert documents once. Give agents only what they need.

DocSift converts PDFs and Office documents into clean, structured, AI-ready
Markdown and JSON — locally, with no cloud APIs. Docling handles PDFs;
MarkItDown handles the breadth formats; both sit behind one interface.

**v0.2.0**

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

## HTTP API

    pip install "docsift[api]"
    docsift serve

Then convert a document asynchronously:

    # returns 202 with {"job_id": "...", "document_id": "...", "status": "queued"}
    curl -sS -F file=@report.pdf http://127.0.0.1:8000/v1/documents

    # poll until "succeeded" or "failed"
    curl -sS http://127.0.0.1:8000/v1/jobs/job_xxxxxxxxxxxxxxxx

    # then fetch the result
    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/markdown
    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/chunks

Conversion always runs in the background — a long PDF can take minutes, and
clients that assume a synchronous response will time out. The OpenAPI document
is at `/openapi.json`.

State lives in `DOCSIFT_DATA_DIR` (default `~/.local/share/docsift`): a SQLite
database of jobs and documents, plus stored artifacts. Uploads are capped at
50 MB via `DOCSIFT_MAX_UPLOAD_BYTES`. `DELETE /v1/documents/{id}` removes the
stored document and its database record, and also purges any cached
conversion results for it, so deletion is genuine rather than leaving a copy
recoverable from the cache.

**Running untrusted documents:** the service converts whatever it is given.
Run it on infrastructure you control, behind your own authentication — DocSift
has none of its own — and prefer the container, which runs as a non-root user.

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
- The API has no authentication, rate limiting or multi-tenancy. Do not expose
  it directly to the internet.
- Search and comparison endpoints are not implemented yet.

## License

MIT
