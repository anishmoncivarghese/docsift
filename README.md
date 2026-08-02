# DocSift

> Convert documents once. Give agents only what they need.

DocSift converts PDFs and Office documents into clean, structured, AI-ready
Markdown and JSON — locally, with no cloud APIs. Docling handles PDFs;
MarkItDown handles the breadth formats; both sit behind one interface.

Status: pre-release (v0.1 in development). See `docs/specs/v0.1-spec.md`.

## Install (development)

    uv sync --all-extras

## Usage

    uv run docsift convert report.pdf
    uv run docsift convert report.pdf --engine markitdown
    uv run docsift --version
    uv run docsift compare report.pdf
    uv run docsift compare report.pdf --output ./comparison

`compare` runs every engine on the same document and writes
`<name>.compare.json` (machine-readable metrics) and `<name>.compare.md`
(human-readable report) alongside per-engine output folders.

Output defaults to `./output/` and can be changed with `--output DIR`.

## Chunking and cleaning

Conversion cleans the Markdown (repeated headers/footers, page numbers, image
references) and splits it into token-budgeted chunks with heading context:

    uv run docsift convert report.pdf --max-tokens 800 --overlap 100
    uv run docsift convert report.pdf --keep-image-refs
    uv run docsift convert report.pdf --no-cache

Results are cached in `~/.cache/docsift` (override with `DOCSIFT_CACHE_DIR`);
an unchanged file with unchanged settings returns instantly.

## License

MIT
