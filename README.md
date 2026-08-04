# DocSift

> Convert documents once. Give agents only what they need.

DocSift converts PDFs and Office documents into clean, structured, AI-ready
Markdown and JSON — locally, with no cloud APIs. Docling handles PDFs;
MarkItDown handles the breadth formats; both sit behind one interface.

**v0.1.1**

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

## Known limitations

- `--overlap` applies to the fallback Markdown chunker only. Docling supplies
  its own chunks for PDFs, and DocSift warns when the option cannot take effect.
- Cleaning removes little from Docling-parsed PDFs, because Docling already
  drops page headers and footers using its layout model. The cleaning stages
  earn their keep on MarkItDown output (Word, HTML, spreadsheets).
- The result cache in `~/.cache/docsift` has no automatic eviction. Use
  `docsift cache info` and `docsift cache clear` to manage it.
- A GFM table written without a leading `|` is not recognised as a table and
  its rows are not protected from de-duplication. Both bundled engines emit
  pipe-prefixed tables, so this affects hand-written Markdown only.

## License

MIT
