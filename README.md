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

Output defaults to `./output/` and can be changed with `--output DIR`.

## License

MIT
