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

Pick the engine you need — `markitdown` for Word, Excel, PowerPoint, HTML, CSV
and EPUB; `docling` for PDFs (a large download: ML layout models); `all` for both
engines plus the HTTP API and MCP server.

    pip install "docsift[markitdown]"
    pip install "docsift[docling]"
    pip install "docsift[all]"

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

Check it landed. Run these one at a time; the second prints the path to the
executable, which the next step needs.

    docsift --version

    which docsift

### 2. Register it with your client

**Pick the one you use. You only need one of these.**

#### Claude Code

`$(which docsift)` fills in the path for you, so this works exactly as written:

    claude mcp add --scope user docsift -- "$(which docsift)" mcp

Then confirm it started — look for `docsift ... ✔ Connected`:

    claude mcp list

`--scope user` makes it available in every project; without it, the server is
registered only for the directory you were in.

**That is the whole setup for Claude Code.** Skip the next part and go to step 3.

#### Claude Desktop, Codex, Cursor

These read a JSON config file instead. For Claude Desktop on macOS that is
`~/Library/Application Support/Claude/claude_desktop_config.json`; create it if
it does not exist.

If the file is empty or new, this is the whole contents — replacing the command
with the path `which docsift` printed in step 1:

```json
{
  "mcpServers": {
    "docsift": {
      "command": "/replace/with/the/path/from/which/docsift",
      "args": ["mcp"]
    }
  }
}
```

If it already has other servers, add `docsift` beside them rather than replacing
the file — note the comma after the previous entry:

```json
{
  "mcpServers": {
    "something-you-already-had": {
      "command": "..."
    },
    "docsift": {
      "command": "/replace/with/the/path/from/which/docsift",
      "args": ["mcp"]
    }
  }
}
```

Use the absolute path, not a bare `docsift`. These clients do not reliably
inherit your shell's `PATH`, and a wrong or bare path fails with `ENOENT: no
such file or directory`.

Then **restart the app** — the config is read at startup.

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

Then ask your assistant, naming the tool:

> use the docsift search_document tool on /tmp/docsift-check.md to search for
> "passages"

**Name it explicitly, and watch which tool actually runs.** Asked casually, an
assistant will often just open a small file with its own file-reading tool and
answer from that — you get the right answer having never touched DocSift, which
makes a broken setup look like a working one. If your assistant reports reading
a file rather than calling `docsift`, the check has told you nothing.

The first call will ask your permission to run the tool — approve it, and choose
the "don't ask again" option if your client offers one, so later questions are
not interrupted mid-thought.

Success looks like a `docsift` tool call in the transcript, returning that one
sentence. This needs no PDF and no model weights, so a failure here is a setup
problem — the command not on `PATH`, or the server not registered — and not a
conversion one.

Then try a real PDF of your own, and expect the first question to take a minute.
On a document of that size the choice takes care of itself: reading it whole is
expensive, which is when searching it becomes the obvious move.

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
    docsift inspect report.pdf
    docsift compare report.pdf
    docsift search doc_xxxxxxxxxxxx "operational risk"
    docsift search doc_xxxxxxxxxxxx '"operational risk"' --limit 5 --context 1
    docsift cache info
    docsift cache clear

`inspect` reports what DocSift would do with a file — engine, identity, cache
status — without converting it. `compare` runs both engines on the same document
and writes a diff of the results.

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

Upload, and get back `202` with a job id and a document id:

    curl -sS -F file=@report.pdf http://127.0.0.1:8000/v1/documents

Poll until the status is `succeeded` or `failed`:

    curl -sS http://127.0.0.1:8000/v1/jobs/job_xxxxxxxxxxxxxxxx

Then retrieve the whole document:

    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/markdown
    curl -sS http://127.0.0.1:8000/v1/documents/doc_xxxxxxxxxxxx/chunks

Or ask a question and get only the relevant chunks:

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
