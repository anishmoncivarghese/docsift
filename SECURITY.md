# Security policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: go to the **Security** tab of this
repository and choose **Report a vulnerability**. That opens a channel visible
only to the maintainer.

Please do not open a public issue for something exploitable.

DocSift is maintained by one person. Expect an acknowledgement within a week,
and please assume good faith rather than indifference if it takes longer. There
is no paid support tier and no response-time guarantee.

## Supported versions

DocSift is pre-1.0. Only the most recent release receives fixes. There are no
backports to earlier 0.x versions.

## What DocSift assumes

Understanding these is more useful than a list of CVEs, because most of them are
design choices rather than defects.

**The service is meant to run on infrastructure you control.** `DOCSIFT_API_KEY`
is a single shared secret. It is not identity: there are no users, no roles, no
rate limiting and no multi-tenancy. Anyone holding the key can read and delete
anything the service holds.

**Document ids are content hashes, not capability tokens.** Two callers who
upload the same bytes get the same document, and either can retrieve or delete
it. Do not treat a document id as a secret or as an access control boundary.

**Untrusted documents are the main attack surface.** DocSift does not parse
documents itself — it delegates to Docling and MarkItDown, which pull in PDF,
Office, XML and zip parsers. A malicious document is handled by those libraries
with no sandboxing and no resource ceiling beyond the upload size limit.
Conversions run with no timeout, and `.zip` expansion is not bounded by a
decompression ratio. If you accept documents from strangers, isolate the
process.

**Engine errors never quote document content.** Conversion failures surface only
the exception type, because exception text routinely embeds fragments of the
document. Preserve that property in any change you make to error handling.

The full list of behavioural limits — single-process constraints, buffering
behaviour on uploads without `Content-Length`, deleted text lingering in
unvacuumed SQLite pages — lives in [docs/LIMITATIONS.md](docs/LIMITATIONS.md). They
are documented rather than hidden, and a report that simply restates one is not
a vulnerability report.

## In scope

- Retrieving or deleting a document without the configured API key.
- Reading one document's content through a request scoped to another.
- Document content appearing in an error response, a log line, or an API
  document.
- Escaping the intended data directory when writing or reading artifacts.
- Anything that lets a crafted document execute code in the DocSift process.

## Out of scope

- Denial of service through a deliberately expensive document. This is known,
  documented, and inherent to running conversion without a timeout.
- Anything requiring the API key, on a deployment where the key is the only
  intended boundary.
- Findings against a deployment exposed to the public internet without a key.
  That configuration is documented as unsupported.
