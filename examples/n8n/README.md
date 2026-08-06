# DocSift in n8n

`docsift-convert-and-search.json` uploads a document, waits for conversion to
finish, then runs a keyword search and returns the matching chunks.

## Import

n8n → **Workflows** → **Import from File** → choose the JSON.

## Set the values in the "Settings" node

| Field | What to put |
|---|---|
| `baseUrl` | Where DocSift is reachable, e.g. `https://docsift.internal` |
| `apiKey` | Your `DOCSIFT_API_KEY`, or leave empty if the service has none |
| `query` | The search query to run once conversion finishes |
| `maxPolls` | Maximum status checks before the workflow stops (default: 60) |

## Supply the document

The imported workflow runs immediately: **Create sample document** produces a
small text file in the binary field named `data`, and **Upload document** sends
that field to DocSift. For a real workflow, replace **Create sample document**
with any binary-producing node — *Read/Write Files from Disk*, an email
attachment, or a webhook upload — and keep its binary property named `data`.

## How the polling loop works

Conversion runs in the background and can take minutes on a long PDF, so the
workflow waits five seconds, checks the job, and loops back while it is still
pending or running. **Conversion failed?** stops the execution as soon as
DocSift reports a failed job. **Polling limit reached?** also stops the workflow
after `maxPolls` checks, so an unexpected status or stalled job cannot loop
forever. With the defaults, the maximum polling window is about five minutes.
