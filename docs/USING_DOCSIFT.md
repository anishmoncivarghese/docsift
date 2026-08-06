# Using DocSift

A practical guide: calling it from Python, running it as a service, choosing
where to host it, and testing it in Copilot Studio and Power Automate.

DocSift is on PyPI as [`docsift`](https://pypi.org/project/docsift/); the source
is at <https://github.com/anishmoncivarghese/docsift>. Current version: **0.4.0**.

---

## 1. Install

DocSift needs at least one conversion engine. Installing the bare package gives
you the command-line tool but nothing that can read a document.

```bash
pip install "docsift[markitdown]"   # Word, Excel, PowerPoint, HTML, CSV, EPUB
pip install "docsift[docling]"      # PDFs — large download, includes ML layout models
pip install "docsift[all]"          # both, plus the HTTP API
```

For the HTTP API specifically you need `[api]`, which `[all]` already includes:

```bash
pip install "docsift[all]"
```

The first PDF conversion downloads Docling's layout models (a few hundred MB).
That happens once; afterwards everything runs offline.

---

## 2. Calling DocSift from Python

Everything below has been run against the published 0.4.0 package — these are
real outputs, not illustrations.

### Convert a document

```python
from pathlib import Path
from docsift.services.conversion_service import convert_document

result = convert_document(Path("report.html"))

print(result.document_id)                    # doc_d8ce510ec576
print(result.conversion.engine)              # markitdown
print(result.metrics.estimated_tokens)       # 26
print(len(result.chunks))                    # 1
print(result.document.markdown[:40])         # '# Quarterly Report\n\nRevenue grew across '

for chunk in result.chunks:
    print(chunk.chunk_id, chunk.section_path, chunk.estimated_tokens)
    # doc_d8ce510ec576_c000 ['Quarterly Report'] 26
```

`convert_document` picks the engine from the file type — PDFs go to Docling,
everything else to MarkItDown — cleans the Markdown, splits it into chunks, and
counts tokens. It returns a `ConversionResult`.

### The full signature

```python
convert_document(
    path: Path,
    engine: str = "auto",              # "auto" | "docling" | "markitdown"
    output_dir: Path | None = None,    # also write <stem>.md and <stem>.docsift.json here
    options: ConversionOptions | None = None,
    use_cache: bool = True,
) -> ConversionResult
```

### What you get back

| Attribute | What it holds |
|---|---|
| `result.document_id` | `doc_` plus 12 hex characters, derived from the file's content |
| `result.document.markdown` | The cleaned Markdown |
| `result.document.page_count` | Pages, when the engine reports them |
| `result.chunks` | List of `Chunk` — see below |
| `result.metrics` | `characters`, `words`, `estimated_tokens`, `raw_estimated_tokens`, `duplicate_lines_removed` |
| `result.conversion` | `engine`, `engine_version`, `duration_ms`, `cached`, `selection_reason` |
| `result.source` | `filename`, `media_type`, `size_bytes`, `sha256` |
| `result.warnings` | List of `ConversionWarning` with `code` and `message` |

Each `Chunk` has `chunk_id`, `text`, `estimated_tokens`, `section_path` (the
heading trail, e.g. `["Risk Report", "Operational Risk"]`) and `pages`.

### Controlling chunking and cleaning

```python
from docsift.core.options import ConversionOptions, ChunkOptions, CleanOptions

options = ConversionOptions(
    chunk=ChunkOptions(max_tokens=800, overlap_tokens=100),
    clean=CleanOptions(
        remove_image_refs=True,      # drop image-only lines
        keep_page_markers=True,      # keep <!-- page: N --> comments
        remove_furniture=True,       # strip repeated headers/footers
        furniture_min_repeats=3,     # how many repeats before a line counts as furniture
    ),
)

result = convert_document(Path("report.pdf"), options=options)
```

`overlap_tokens` applies only to DocSift's own chunker. Docling supplies its own
chunks for PDFs and has no overlap concept — you get a warning when the option
cannot take effect.

### Check a file without converting it

```python
from docsift.services.inspection_service import inspect_document

info = inspect_document(Path("report.pdf"))
print(info.engine)              # docling
print(info.engine_available)    # False if the docling extra isn't installed
print(info.cached)              # True if this exact file+settings was converted before
print(info.source.size_bytes)
```

Useful for deciding whether a conversion is worth starting, and for diagnosing
why a conversion isn't working.

### Handling errors

Every DocSift failure inherits from one base class:

```python
from docsift.core.exceptions import (
    DocSiftError,              # base — catch this to catch everything
    UnsupportedFileError,      # missing, empty, too large, or unsupported type
    EngineNotAvailableError,   # the engine for this file type isn't installed
    ConversionFailedError,     # the engine failed on this document
)

try:
    result = convert_document(Path("broken.pdf"))
except UnsupportedFileError as exc:
    print("cannot process this file:", exc)
except DocSiftError as exc:
    print("conversion failed:", exc)
```

Error messages never contain document text — engine failures are reduced to the
exception type name. That is deliberate: it means you can log these safely.

### Searching

Search works over documents stored by the **HTTP service**, not by
`convert_document`. Converting a file in Python writes standalone output; it does
not add the document to the service's store or its search index. If you want
search, upload through the API (section 3).

```python
from docsift.services.search_service import search_document

response = search_document(
    "doc_d8ce510ec576",
    "operational risk",
    limit=5,          # direct matches, 1–20
    max_tokens=5000,  # cap on the whole response, 1–20000
    context=0,        # adjacent chunks either side, 0–2
)

for hit in response.results:
    print(hit.chunk_id, hit.section_path, hit.pages, round(hit.score, 3), hit.match)
```

`match=True` marks a direct hit; `match=False` means the chunk was pulled in as
context and `context_for` names the hit it belongs to. `score` orders results
within one response only — it is not comparable across requests.

### A note on caching

Results are cached in `~/.cache/docsift`, keyed on file content, engine version,
DocSift version and your options. Converting the same file twice returns
instantly. Override the location with `DOCSIFT_CACHE_DIR`, disable per-call with
`use_cache=False`, and manage it with `docsift cache info` / `docsift cache clear`.

---

## 3. Running the HTTP service

```bash
pip install "docsift[all]"
docsift serve                     # http://127.0.0.1:8000
```

Conversion is **asynchronous by design**. Upload returns immediately with a job
id; you poll until it finishes. A long PDF can take minutes, and Power Platform
connectors time out at roughly 120 seconds — a synchronous API would fail on
exactly the documents this tool exists for.

```bash
# 1. upload — returns 202 immediately
curl -sS -F file=@report.pdf http://127.0.0.1:8000/v1/documents
# {"job_id":"job_9ae0127fe030","document_id":"doc_c3c74e5ebab3","status":"queued"}

# 2. poll until "succeeded" or "failed"
curl -sS http://127.0.0.1:8000/v1/jobs/job_9ae0127fe030

# 3. retrieve
curl -sS http://127.0.0.1:8000/v1/documents/doc_c3c74e5ebab3/markdown
curl -sS http://127.0.0.1:8000/v1/documents/doc_c3c74e5ebab3/chunks

# 4. search
curl -sS --get --data-urlencode 'q=operational risk' \
  --data 'limit=5' --data 'max_tokens=5000' \
  http://127.0.0.1:8000/v1/documents/doc_c3c74e5ebab3/search
```

### Turn on the API key before anyone else can reach it

```bash
DOCSIFT_API_KEY=$(openssl rand -hex 24) docsift serve
curl -H "X-API-Key: your-secret" http://127.0.0.1:8000/v1/documents/...
```

Every route requires the header except `/health`, `/version`, `/openapi.json`,
`/docs` and `/redoc`, which stay open so health checks and connector imports keep
working. This is **one shared secret for the whole service** — not per-user
identity. It is the minimum for a service other tools can reach, not a substitute
for network controls.

### Settings

| Variable | Default | What it does |
|---|---|---|
| `DOCSIFT_API_KEY` | unset | Requires `X-API-Key` on protected routes |
| `DOCSIFT_PUBLIC_URL` | unset | Address advertised to connectors — **set this before generating a connector file** |
| `DOCSIFT_DATA_DIR` | `~/.local/share/docsift` | SQLite database, stored documents, search index |
| `DOCSIFT_CACHE_DIR` | `~/.cache/docsift` | Conversion cache (disposable) |
| `DOCSIFT_MAX_UPLOAD_BYTES` | 52428800 (50 MB) | Upload ceiling |
| `DOCSIFT_JOB_WORKERS` | 2 | Concurrent conversions |
| `DOCSIFT_MAX_PENDING_JOBS` | 32 | Queue depth before returning 503 |

---

## 4. Where to host it

Copilot Studio runs in Microsoft's cloud. It cannot reach your laptop, so the
service has to live somewhere with an address your tenant can call.

**Recommended: Azure Container Apps or an Azure App Service**, inside the same
tenant as your Copilot Studio environment. That keeps documents within the
Microsoft boundary you already trust and gives you a TLS address for free.
Budget roughly **$15–40/month** for something with enough memory for Docling
(4–8 GB).

Whatever you choose, three things matter:

1. **HTTPS.** Power Platform will not call a plain-HTTP host.
2. **Set `DOCSIFT_API_KEY`.** Without it, anyone who learns the URL can upload,
   read and delete documents.
3. **Persist `DOCSIFT_DATA_DIR`.** It holds the SQLite database, the stored
   documents and the search index. On a container platform this needs a mounted
   volume — otherwise every restart loses every document.

You do **not** need Docker. `pip install "docsift[all]"` plus `docsift serve`
works on any Linux host, and Azure App Service can deploy Python straight from a
repository. A `Dockerfile` is included but has never been build-tested — treat it
as a starting point rather than a proven artifact.

### About the GitHub repository

The repo is private today. Publishing to PyPI already makes the *code* readable
by anyone who installs the package, so keeping the repo private hides only the
commit history, branches and issues. If you want the open-source benefits —
contributors, stars, credibility — making it public costs nothing you have not
already given away. That is a positioning decision, not a technical one.

---

## 5. Testing in Power Platform and Copilot Studio

This is the part that needs your tenant. Nothing below has been executed — the
connector file validates against the Swagger 2.0 schema, but no one has imported
it into a live Power Platform environment yet. Expect to hit at least one snag;
the troubleshooting section covers the likely ones.

### Step 1 — deploy DocSift somewhere reachable

Get the service running with HTTPS and an API key, and confirm from your own
machine:

```bash
curl https://docsift.yourcompany.com/health
# {"status":"ok"}
```

If that does not work from outside your network, nothing after this will.

### Step 2 — generate the connector file

Run this **with `DOCSIFT_PUBLIC_URL` set to the deployed address**. The value
becomes the connector's host; a file generated with the default points at
`127.0.0.1` and will fail from the cloud.

```bash
DOCSIFT_PUBLIC_URL=https://docsift.yourcompany.com \
  docsift openapi --format swagger2 -o docsift-connector.json
```

Sanity-check it before uploading:

```bash
python -c "import json; d=json.load(open('docsift-connector.json')); \
print(d['swagger'], d['host'], d['schemes'])"
# 2.0 docsift.yourcompany.com ['https']
```

**Why not just use `/openapi.json`?** The service serves OpenAPI 3.1. Power
Platform custom connectors require Swagger 2.0. Uploading the live document fails
with an unhelpful error — this command exists specifically to bridge that gap.

### Step 3 — create the custom connector

1. Go to <https://make.powerapps.com> and pick the right environment (top right).
2. **Custom connectors** in the left nav → **+ New custom connector** →
   **Import an OpenAPI file**.
3. Name it `DocSift`, choose `docsift-connector.json`, **Continue**.
4. **General** tab: confirm the host reads `docsift.yourcompany.com` and the
   scheme is HTTPS.
5. **Security** tab: choose **API Key**, then set
   - Parameter label: `API Key`
   - Parameter name: `X-API-Key`
   - Parameter location: `Header`
6. **Definition** tab: you should see nine operations —
   `uploadDocument`, `getJobStatus`, `getDocument`, `getDocumentMarkdown`,
   `getDocumentChunks`, `searchDocument`, `deleteDocument`, `getHealth`,
   `getVersion`.
7. **Create connector** (top right).

### Step 4 — test the connector

On the **Test** tab:

1. **+ New connection**, paste your `DOCSIFT_API_KEY`, **Create connection**.
2. Test `getHealth` first — it takes no parameters. You want `200` and
   `{"status":"ok"}`. If this fails, the problem is networking or the host value,
   not DocSift.
3. Test `searchDocument` with a `document_id` you have already converted and any
   `q`. You want `200` and a `results` array.

Getting these two green means the connector works. Everything after this is
about how you use it.

### Step 5 — the Power Automate flow that uploads and waits

A Copilot Studio action calls a connector **once**. It cannot loop. Conversion is
asynchronous and can take minutes, so uploading needs a flow.

In <https://make.powerautomate.com> → **+ Create** → **Instant cloud flow**:

1. **Trigger** — *Manually trigger a flow* to start with, or *When a file is
   created* in SharePoint for the real thing.
2. **DocSift — uploadDocument**
   - `file`: the file content
   - `engine`: leave `auto`
   - Note the outputs: `job_id` and `document_id`
3. **Initialize variable** — name `jobStatus`, type String, value `queued`
4. **Do until** — condition: `jobStatus` **is equal to** `succeeded`
   Under *Change limits*: Count `60`, Timeout `PT30M`
   Inside the loop, in this order:
   - **Delay** — 5 seconds. *Without this the loop burns its 60 iterations in
     seconds and gives up before conversion finishes.*
   - **DocSift — getJobStatus** with `job_id` from step 2
   - **Set variable** `jobStatus` to the `status` output
   - **Condition** — if `jobStatus` equals `failed`, **Terminate** as Failed with
     the job's `error`. *Without this the loop runs the full 30 minutes on a
     document that failed in 10 seconds.*
5. **DocSift — searchDocument** — `document_id` from step 2, `q` your query
6. **Respond** with the `results` array

Test it with a small file first. A one-page Word document converts in seconds; a
100-page scanned PDF is the wrong thing to debug with.

### Step 6 — wire it into Copilot Studio

At <https://copilotstudio.microsoft.com>, open your agent → **Actions** →
**+ Add an action**.

**Add `searchDocument` as a connector action.** This is the one an agent actually
needs mid-conversation: it returns only the chunks relevant to a question,
already token-budgeted, with page and section metadata you can cite. It answers
in milliseconds — comfortably inside connector timeouts.

Describe the inputs so the agent fills them sensibly:

- `document_id` — "the document to search, from your document list"
- `q` — "keywords or a quoted phrase from the user's question"

**Add the Power Automate flow from Step 5** as a separate action if the agent
needs to ingest documents during a conversation. Do not try to make a single
action upload and wait; it will time out on exactly the large documents this tool
exists to handle.

### What "working" looks like

Ask your agent a question about a document you have converted. It should call
`searchDocument`, get back three to five chunks, and answer from those —
citing pages. If it answers from the whole document, check that you exposed
`searchDocument` rather than `getDocumentMarkdown`.

---

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Connector import fails with an unhelpful error | You uploaded `/openapi.json` (OpenAPI 3.1). Use `docsift openapi --format swagger2`. |
| Every call returns 401 | The connection has no key, or the key does not match `DOCSIFT_API_KEY`. Check for trailing whitespace in the environment variable. |
| Calls time out from the cloud but work locally | The connector host is `127.0.0.1`. Regenerate with `DOCSIFT_PUBLIC_URL` set. |
| Upload returns 202, then the document 404s | Conversion has not finished. Poll `getJobStatus` until `succeeded`. |
| Job status stays `queued` | No worker is free. Check `DOCSIFT_JOB_WORKERS`; a large PDF may be occupying both. |
| Upload returns 503 | The queue is full (`DOCSIFT_MAX_PENDING_JOBS`). Retry shortly. |
| Search returns 409 | The document was converted before v0.3.0 and is not in the index. Re-upload it. |
| Search returns `results: []` for something you know is there | Search is lexical, not semantic — it does not know synonyms. Try the document's actual wording. |
| Documents vanish after a restart | `DOCSIFT_DATA_DIR` is not on persistent storage. Mount a volume. |
| PDFs fail, Office files work | The `docling` extra is not installed. `pip install "docsift[all]"`. |

---

## 7. Known limitations

Worth reading before you rely on this in front of colleagues.

- **No per-user identity.** One shared API key for the whole service, no rate
  limiting, no multi-tenancy. Run it behind your own network controls.
- **A Copilot Studio action cannot poll.** Search is a direct connector call;
  uploading needs a Power Automate flow.
- **Search is lexical.** No synonyms, no semantic matching, one document at a
  time. Semantic search is planned but not built.
- **Cleaning removes little from PDFs.** Docling already strips headers and
  footers with its layout model, so DocSift's cleaning mostly earns its keep on
  Word and HTML. The token savings come from search returning a few chunks
  instead of a whole document — not from cleaning.
- **No processing timeout.** A pathological document can occupy a worker
  indefinitely.
- **Document ids are content hashes.** Two people uploading identical files share
  one document, and either can delete it.
- **The Dockerfile has never been built.** Verify it yourself before relying on
  containers.
- **The connector has never been imported into a live tenant.** The file is
  schema-valid; Step 5 above is the first real test.
