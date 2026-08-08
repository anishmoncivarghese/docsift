# DocSift

> Convert documents once. Give agents only what they need.

A 300-page PDF does not fit in a language model's context window, and pasting it
in would be expensive if it did. DocSift converts documents into clean Markdown
once, indexes them, and then hands back only the passages that answer a
question — with page numbers and section headings, so the answer can be cited.

It runs on your machine. PDFs go through [Docling](https://github.com/docling-project/docling),
everything else through [MarkItDown](https://github.com/microsoft/markitdown),
both behind one interface. No cloud APIs, no accounts, no telemetry.

**Where the saving comes from:** retrieval, not conversion. Cleaning barely
reduces tokens on PDFs, because Docling already strips headers and footers with
its layout model. What changes the bill is asking a question and getting three
relevant chunks back instead of a whole document.

## Quickstart

    pip install "docsift[markitdown]"    # Word, Excel, PowerPoint, HTML, CSV, EPUB
    pip install "docsift[docling]"       # PDFs (large: ML layout models)
    pip install "docsift[all]"           # both engines, the HTTP API and MCP

    docsift convert report.pdf

That writes cleaned Markdown, token-budgeted chunks and a JSON summary to
`./output/`. `pip install docsift` on its own installs the CLI but no engine, and
conversion will tell you so rather than failing obscurely.

## Use it from Claude, Codex, or another MCP client

The shortest path to the point of this tool: let an assistant search your own
documents, without pasting them anywhere.

    pip install "docsift[mcp,docling,markitdown]"
    claude mcp add docsift -- docsift mcp

For Claude Desktop, Codex, Cursor and others, add it to the client's config:

```json
{
  "mcpServers": {
    "docsift": {
      "command": "docsift",
      "args": ["mcp"]
    }
  }
}
```

If the client cannot find it, use the absolute path from `which docsift` — MCP
clients do not always inherit your shell's `PATH`.

Two tools are exposed:

- **`search_document`** — the one that matters. Give it a file path and a
  question; it converts the file the first time it sees it, then returns only
  the passages that match. This is what keeps a long PDF out of the context
  window.
- **`convert_document`** — converts and indexes a file, returning a summary
  (page count, token estimate, chunk count) rather than the text.

Everything happens in that process, on your machine. Nothing listens on a port
and no document content crosses the network. The server has exactly the
filesystem access of the user who started it.

## Command line

    docsift convert report.pdf --max-tokens 800 --overlap 100
    docsift convert report.pdf --engine markitdown
    docsift inspect report.pdf                     # what it would do, without converting
    docsift compare report.pdf                     # run both engines, diff the results
    docsift search doc_xxxxxxxxxxxx "operational risk"
    docsift search doc_xxxxxxxxxxxx '"operational risk"' --limit 5 --context 1
    docsift cache info
    docsift cache clear

Conversion cleans repeated headers and footers, page numbers and image
references, then splits the text into token-budgeted chunks that carry their
heading context. `--keep-furniture` and `--keep-image-refs` turn the cleaning
stages off.

Results are cached, so an unchanged file with unchanged settings returns
instantly. `--no-cache` forces a re-run.

Search is local SQLite FTS5 keyword ranking with quoted-phrase support. It reads
the store the HTTP service and the MCP server write to — `docsift convert`
writes standalone files to an output directory and does not add them to it.
`--context` pulls in adjacent chunks, `--max-tokens` caps the whole response, and
only selected chunks are ever printed. Scores order results within one response
and are not comparable across requests.

## HTTP API

    pip install "docsift[all]"
    docsift serve

Conversion always runs in the background: a long PDF can take minutes, and a
client expecting a synchronous response will time out.

    # 202 with {"job_id": ..., "document_id": ..., "status": "queued"}
    curl -sS -F file=@report.pdf http://127.0.0.1:8000/v1/documents

    # poll until "succeeded" or "failed"
    curl -sS http://127.0.0.1:8000/v1/jobs/job_xxxxxxxxxxxxxxxx

    # then retrieve
    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/markdown
    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/chunks

    # or ask a question and get only the relevant chunks
    curl -sS --get --data-urlencode 'q=operational risk' \
      --data 'limit=5' --data 'max_tokens=5000' \
      http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/search

`DELETE /v1/documents/{id}` removes the document, its search index and its cached
conversions — including cancelling a conversion still in flight, so a delete
cannot be undone by a worker finishing afterwards. The OpenAPI document is at
`/openapi.json`.

**Set `DOCSIFT_API_KEY` before anything else can reach it.** Every `/v1/*` route
then requires an `X-API-Key` header, while `/health`, `/version` and the API docs
stay open for health checks and connector imports. It is one shared secret for
the whole service — not per-user identity, and no substitute for network
controls. The service converts whatever it is given, so run it on infrastructure
you control.

## Power Platform, Copilot Studio and n8n

    DOCSIFT_PUBLIC_URL=https://docsift.example docsift openapi --format swagger2 -o connector.json

Import that as a Power Platform custom connector. The service's own
`/openapi.json` is OpenAPI 3.1, which custom connectors reject; this command
emits the Swagger 2.0 they accept. Verified against a real tenant: the file
imports, authenticates and returns schema-valid responses.

Worked examples live in
[`examples/`](https://github.com/anishmoncivarghese/docsift/blob/main/examples/)
— an importable n8n workflow, a Copilot Studio connector walkthrough, and the
Power Automate *Do until* flow that waits for a conversion. A longer guide is in
[docs/USING_DOCSIFT.md](https://github.com/anishmoncivarghese/docsift/blob/main/docs/USING_DOCSIFT.md).

## More

| | |
|---|---|
| [Known limitations](https://github.com/anishmoncivarghese/docsift/blob/main/docs/LIMITATIONS.md) | What DocSift does not do, stated plainly. Worth reading before you rely on it. |
| [Configuration](https://github.com/anishmoncivarghese/docsift/blob/main/docs/CONFIGURATION.md) | Every environment variable. |
| [Docker](https://github.com/anishmoncivarghese/docsift/blob/main/docs/DOCKER.md) | Running the service in a container. |
| [Deploying to Azure](https://github.com/anishmoncivarghese/docsift/blob/main/docs/DEPLOY_AZURE.md) | A hosted deployment, end to end. |
| [Privacy](https://github.com/anishmoncivarghese/docsift/blob/main/PRIVACY.md) | What lands on disk, and the three times the network is touched. |
| [Security](https://github.com/anishmoncivarghese/docsift/blob/main/SECURITY.md) | The threat model, and how to report a vulnerability. |
| [Contributing](https://github.com/anishmoncivarghese/docsift/blob/main/CONTRIBUTING.md) | Setup, the gates, and what review looks for. |
| [Changelog](https://github.com/anishmoncivarghese/docsift/blob/main/CHANGELOG.md) | What shipped, and when. |

## License

MIT
