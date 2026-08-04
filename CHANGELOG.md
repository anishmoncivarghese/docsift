# Changelog

## 0.1.1 — 2026-08-03

Closes the limitations documented in 0.1.0.

- Cleaning decisions now apply to engine-supplied chunks, so chunk text from
  Docling-parsed PDFs no longer keeps the headers, footers, page numbers and
  image references stripped from the Markdown. Chunks left empty by cleaning
  are dropped and token counts are recomputed.
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
- A two-line pseudo-table no longer loses a row when split.

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
