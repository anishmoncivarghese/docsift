# Known limitations

Everything DocSift does not do, or does with a caveat. This list is deliberately
blunt: a documented limit is worth more than a quiet surprise.

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
