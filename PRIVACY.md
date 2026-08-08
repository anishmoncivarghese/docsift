# Privacy

DocSift is software you run. There is no DocSift service, no account, no
sign-up, and no server operated by the maintainer. Nothing here describes a
company handling your data, because there isn't one.

## Your documents stay where you run it

DocSift never transmits document content anywhere. Conversion happens in the
process you started, and results are written to disk on the machine that runs
it:

| What | Where |
|---|---|
| Converted Markdown and chunks | `DOCSIFT_DATA_DIR` (API), or the output path you pass (CLI) |
| Job and document records, search index | `docsift.db` in the data directory |
| Conversion cache | `DOCSIFT_CACHE_DIR`, default `~/.cache/docsift` |

The search index holds a second copy of your document's text, since that is what
makes retrieval possible.

## There is no telemetry

No usage reporting, no crash reporting, no analytics, no update check. DocSift
does not phone home, and there is no setting to turn off because there is
nothing to turn off.

## When DocSift does use the network

Three cases, none of which send your content anywhere:

- **Installation** downloads packages from PyPI.
- **First conversion with Docling** downloads model weights from Hugging Face.
  These are *downloads* — your document is not uploaded to obtain them. Once
  cached, conversion runs offline. The Docker image bakes the weights in at
  build time, so a container never needs this.
- **Token estimation** fetches tiktoken's encoding data on first use, then
  caches it.

If you need conversion to run with no outbound access at all, pre-fetch the
models once, or use the Docker image, and the network is no longer touched.

## Deletion

`DELETE /v1/documents/{id}` removes the document record, its stored artifacts,
its rows in the search index, and its entries in the conversion cache. Deletion
during an in-flight conversion cancels that conversion rather than letting it
write the document back afterwards.

One caveat worth knowing: deleted text can remain in unvacuumed SQLite free
pages until the database is `VACUUM`ed. The rows are gone and the API cannot
reach them, but the bytes may still be present on disk. If your threat model
includes someone reading the database file directly, `VACUUM` it.

## If you host DocSift for other people

Then you are the one handling their data, and two properties matter:

**The API key is a single shared secret**, not per-user identity. Everyone with
the key sees everything.

**Document ids are content hashes.** Two people who upload the same file share
one document, and either can retrieve or delete it. On a shared deployment this
means one caller can discover another's document by uploading the same file.

Neither is a bug — they are documented design choices suited to a service run
inside a boundary you control. They make DocSift unsuitable as a multi-tenant
service without work you would have to do yourself.
