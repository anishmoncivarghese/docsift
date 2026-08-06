# DocSift in n8n

`docsift-convert-and-search.json` uploads a document, waits for conversion to
finish, then runs a keyword search and returns the matching chunks.

## Import

n8n → **Workflows** → **Import from File** → choose the JSON.

## Set three values in the "Settings" node

| Field | What to put |
|---|---|
| `baseUrl` | Where DocSift is reachable, e.g. `https://docsift.internal` |
| `apiKey` | Your `DOCSIFT_API_KEY`, or leave empty if the service has none |
| `query` | The search query to run once conversion finishes |

## Supply the document

The **Upload document** node sends the binary field named `data`. Put any node
that produces a binary file before it — *Read Binary File*, an email
attachment, a webhook upload — or use n8n's *Edit Fields* node to attach one for
testing.

## How the polling loop works

Conversion runs in the background and can take minutes on a long PDF, so the
workflow waits five seconds, checks the job, and loops back if it is not
finished. The **Conversion finished?** node's false branch returns to the wait
node. That loop is the whole reason this workflow is more than two HTTP calls —
an integration that assumes conversion is instant will fail on real documents.

If a job fails, the loop keeps polling. Add a second condition on
`{{ $json.status }} equals failed` if you want to break out and handle errors.
