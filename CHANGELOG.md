# Changelog

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
  `--overlap` / `--no-cache`.
