# DocSift

> Convert documents once. Give agents only what they need.

DocSift converts PDFs and Office documents into clean, structured, AI-ready
Markdown and JSON — locally, with no cloud APIs. Docling handles PDFs;
MarkItDown handles the breadth formats; both sit behind one interface.

**v0.1.0**

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

## Known limitations in 0.1.0

- PDF chunks come from Docling's HybridChunker and are built from the raw
  document, so the cleaning stages (header/footer removal, page-number
  stripping) apply to the exported Markdown but **not** to the chunk text on
  that path.
- `--overlap` has no effect on PDFs chunked by Docling; it applies to the
  fallback Markdown chunker used for other file types.
- The result cache in `~/.cache/docsift` has no automatic eviction; delete
  the directory to reclaim space.

## License

MIT
