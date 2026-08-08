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

### 1. Install it as a command, not into a project

An MCP client starts DocSift as a program, so it has to exist outside any
virtualenv. Install it as a standalone tool:

    uv tool install --python 3.12 "docsift[mcp,docling,markitdown]"

or with pipx:

    pipx install --python python3.12 "docsift[mcp,docling,markitdown]"

DocSift needs **Python 3.11 or newer**. If your default is older, the version
flag above is what avoids an unsatisfiable-requirements error. Expect a large
download: `docling` brings PyTorch and layout models.

Check it landed, and note the path — you will need it:

    docsift --version
    which docsift          # e.g. /Users/you/.local/bin/docsift

### 2. Register it with your client

Claude Code:

    claude mcp add --scope user docsift -- /Users/you/.local/bin/docsift mcp
    claude mcp list        # should report: docsift ... ✔ Connected

`--scope user` makes it available in every project; without it, the server is
registered only for the directory you were in.

Claude Desktop, Codex, Cursor and others take a config file — for Claude Desktop
that is `~/Library/Application Support/Claude/claude_desktop_config.json` on
macOS. Add `docsift` alongside anything already there, then restart the app:

```json
{
  "mcpServers": {
    "docsift": {
      "command": "/Users/you/.local/bin/docsift",
      "args": ["mcp"]
    }
  }
}
```

**Use the absolute path from `which docsift`, not a bare `docsift`.** MCP
clients do not reliably inherit your shell's `PATH`, and this is the most common
reason a local server silently fails to start.

### 3. Ask

No commands to learn — describe what you want:

> search ~/Documents/contract.pdf for the termination clause

> what does report.pdf say about Q3 revenue?

The first question about a new file converts it — a minute or two for a long
PDF, while the layout and table models run. That happens once; afterwards the
file is recognised by its content and answers are immediate, even if you move or
rename it.

### 4. Check it works

Before pointing it at a real PDF, prove the wiring with a file that converts
instantly. Make one:

    printf '# Test\n\nDocSift returns only the passages that match a question.\n' > /tmp/docsift-check.md

Then ask your assistant:

> search /tmp/docsift-check.md and tell me what DocSift returns

You should get that one sentence back, having called `search_document`. This
needs no PDF and no model weights, so a failure here is a setup problem — the
command not on `PATH`, or the server not registered — and not a conversion one.

Then try a real PDF of your own, and expect the first question to take a minute.

One test worth running deliberately: **ask about something the document does not
mention.** You should get nothing back rather than a plausible-sounding answer.
Search is lexical, so a word that is not in the text matches nothing — and
seeing that once tells you more about what you can trust than a dozen successful
queries.

### What you get

Two tools:

- **`search_document`** — the one that matters. Give it a file path and a
  question; it converts the file the first time it sees it, then returns only
  the passages that match, with page numbers and section headings.
- **`convert_document`** — converts and indexes a file, returning a summary
  (page count, token estimate, chunk count) rather than the text.

For a sense of scale: a 34-page economic report runs to **21,000 tokens** in
full. Asking it "what does this say about inflation?" returns the five relevant
passages — about **4,000 tokens**, with the pages to cite. That gap is the
entire point, and it widens with document length.

`search_document` takes `limit` and `max_tokens` as well, and a model will set
them when you ask for more or less. The defaults return five passages within a
5,000-token budget. Dense documents produce large chunks — around 1,000 tokens
each in the report above — so if answers feel truncated, a larger `max_tokens`
is the dial, and it is cheaper than the model asking the same question several
times over.

Everything happens in that process, on your machine. Nothing listens on a port
and no document content crosses the network. The server has exactly the
filesystem access of the user who started it.

> **Not in the claude.ai connector directory, and it cannot be.** claude.ai runs
> in the cloud and cannot start a program on your computer. A local MCP server
> works in apps running on your own machine — Claude Code, Claude Desktop, Codex,
> Cursor — and searching the web app's connector list for DocSift will never find
> it.

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
