# Stateless search — candidate specification

**Status: proposed, not scheduled.** A v0.5 candidate. Nothing here is built.

## The problem

Every retrieval path DocSift has today requires the service to hold the
document. `POST /v1/documents` converts and stores; search reads what was
stored. That is the right default, and it is what makes conversion cheap to
amortise across many questions.

It rules out one class of caller: someone who cannot let a document rest on a
server at all — not ours, and not their own. For them, "delete it afterwards" is
not equivalent to "never wrote it down".

## What this adds

One endpoint that converts nothing, stores nothing, and remembers nothing:

    POST /v1/search
    { "markdown": "...", "q": "...", "limit": 5, "max_tokens": 2000, "context": 0 }

It chunks the supplied Markdown in memory, runs the same BM25 ranking the stored
path uses, applies the same token budget, returns the same result shape as
`GET /v1/documents/{id}/search`, and discards everything.

**Markdown in, not PDF in.** This is the design's whole economy. Conversion is
the expensive step — ML models, seconds to minutes, the reason the image is
4.6 GB. Chunking and ranking Markdown needs no model and runs in milliseconds.
A caller converts once (via the CLI, or via the stored API path, or from any
other source), keeps the Markdown, and pays nothing but a fast in-memory search
on each question.

Accepting a PDF here would put a multi-minute ML pipeline behind an endpoint
whose entire premise is that it is cheap to call repeatedly. Callers who want
that already have `POST /v1/documents`.

## Why this does not cost tokens

The Markdown travels from the caller to DocSift over HTTP. It never enters a
model's context. Only the returned chunks do. Sending the whole document on
every request costs bandwidth, not tokens — and bandwidth is not the expensive
resource in an LLM application.

## Requirements

- **SS-1.** `POST /v1/search` accepts `markdown` (required), `q` (required), and
  the same `limit`, `max_tokens` and `context` parameters as the stored search,
  with the same validation and the same 422 behaviour on hostile input.
- **SS-2.** The response body is schema-identical to stored search, minus
  `document_id`. A caller can switch between the two paths without reshaping its
  parsing.
- **SS-3.** Chunking must produce the same chunks the stored path would produce
  for the same Markdown. One chunker, one result — not a second implementation
  that drifts.
- **SS-4.** Nothing is persisted: no row in any table, no file under the data
  directory, no entry in the conversion cache, and nothing in the FTS index.
  This must be asserted by a test that inspects the filesystem and the database
  before and after, not merely by reading the code.
- **SS-5.** The request body is bounded by the same size ceiling that governs
  uploads, and exceeding it returns 413 without buffering the whole body.
- **SS-6.** The endpoint is covered by the API key exactly like every other
  `/v1/*` route. Statelessness is not anonymity.
- **SS-7.** Errors must not echo the submitted Markdown or the query back to the
  caller, consistent with the content-leak guard the rest of the service
  observes.

## Open questions

- **Chunk-level input.** A caller who already holds chunks (from `getDocumentChunks`
  or the CLI) could send those instead of Markdown and skip chunking entirely.
  Cheaper and smaller, but a second input shape to specify and validate. Defer
  until someone asks.
- **Ranking quality on a single document.** BM25 scores are corpus-relative. A
  one-document corpus assembled per request may rank differently than the same
  document inside a stored index. This needs measuring before the endpoint is
  described as equivalent, and the difference documented if it is real.
- **Repeat-cost honesty.** A caller asking twenty questions sends the document
  twenty times. For a large manual over a slow link that may be worse than
  storing it. The documentation should say so plainly rather than selling this
  as strictly better.

## Where this fits, and where it does not

**Fits:** a developer or a backend calling the API directly. The client genuinely
holds the file and can send it.

**Does not fit:** Copilot Studio. An agent action is a stateless call with no
place to keep a document between turns, so the Markdown would have to live in
SharePoint, OneDrive or Dataverse — storage again, just someone else's — and a
document of any size will hit connector payload limits well before it hits
anything interesting.

This endpoint should not be built to serve the Power Platform path. It should be
built when an API caller asks for it.

## Relationship to self-hosting

For most callers who say "our documents must not leave", self-hosting already
answers it and needs no new code: DocSift is open source, the CLI runs entirely
offline, and the service runs inside any network. This endpoint is for the
narrower case where the objection is to *storage itself*, not to location.

That distinction should be clear in any messaging. The stronger, already-true
claim is "run it inside your own network". This is the answer to the rarer
follow-up.
