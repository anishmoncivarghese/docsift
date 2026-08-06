# DocSift as a Copilot Studio custom connector

## 1. Generate the connector file

Power Platform custom connectors take **Swagger 2.0**. DocSift's live
`/openapi.json` is OpenAPI 3.1 and will not import, so generate the Swagger 2.0
version:

    DOCSIFT_PUBLIC_URL=https://docsift.internal docsift openapi --format swagger2 -o docsift-connector.json

Set `DOCSIFT_PUBLIC_URL` to the address Power Platform will call. It becomes the
connector's host, and a connector pointing at `127.0.0.1` will fail from the
cloud.

## 2. Create the connector

1. Go to **Power Apps** → **Custom connectors** → **New custom connector** →
   **Import an OpenAPI file**.
2. Upload `docsift-connector.json`.
3. On the **Security** tab, choose **API Key**, parameter label `API Key`,
   parameter name `X-API-Key`, location `Header`. (Skip this only if the service
   runs with no `DOCSIFT_API_KEY`, which means anyone who reaches the URL can
   use it.)

   The generated connector always declares this API-key header, regardless of
   whether `DOCSIFT_API_KEY` happened to be set in the shell you generated it
   from — you configure the actual key value here, on the Security tab, not by
   regenerating the file.
4. **Create connector**, then **Test** with a connection using your key.

## 3. Use it from Copilot Studio

In your agent: **Actions** → **Add an action** → **Connector** → your DocSift
connector.

**Add `searchDocument` first.** It is the operation an agent actually needs
during a conversation: it returns only the chunks relevant to a question,
already token-budgeted, with page and section metadata for citation. It answers
in milliseconds, well inside connector timeouts.

Give the action inputs the agent can fill: `document_id` from your own record of
the document, and `q` from the user's question.

## 4. Uploading documents needs a Power Automate flow

A Copilot Studio action calls a connector operation **once**. It cannot loop.
DocSift conversion is asynchronous — `uploadDocument` returns a job id
immediately and `getJobStatus` must be polled until it reports `succeeded`,
which can take minutes on a long PDF.

So:

- **Search from Copilot Studio directly.** One call, fast, no loop needed.
- **Upload via a Power Automate flow** with a *Do until* loop, and call that flow
  from Copilot Studio if the agent must ingest a document mid-conversation. See
  `../power-automate/README.md`.

Trying to make a single Copilot Studio action wait for a conversion will hit the
connector timeout (roughly 120 seconds) on exactly the large documents this tool
exists to handle.

## Operation reference

| Operation | Use it for |
|---|---|
| `searchDocument` | Answering a question about a known document — start here |
| `uploadDocument` | Starting a conversion; returns a job id, does not wait |
| `getJobStatus` | Polling until conversion finishes |
| `getDocumentChunks` | Retrieving every chunk when you genuinely need the whole document |
| `getDocumentMarkdown` | Retrieving the whole document as text |
| `deleteDocument` | Removing a document, its index and its cached copies |
