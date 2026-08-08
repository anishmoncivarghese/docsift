# MCP server — specification

**Status: designed, not built.** Proposed as Milestone 7.

## Why this before anything else

One MCP server reaches Claude Desktop, Claude Code, Codex, Cursor and ChatGPT's
connectors. Compare that with Power Platform, which needed a bespoke Swagger 2.0
translator to reach exactly one consumer.

It is also the strongest form of the privacy claim. A local MCP server runs on
the user's machine and calls the DocSift library directly: no service, no
network, no hosting bill. "Your documents never leave your laptop" stops being a
deployment recommendation and becomes a property of how the thing runs.

## Verified SDK facts

Checked against `mcp` **2.0.0** (requires Python >=3.10; DocSift requires
>=3.11) in a throwaway environment on 2026-08-09, because 2.0 changed the API:

- **`mcp.server.fastmcp` no longer exists.** Every `FastMCP` example online
  targets 1.x and will not import. Do not copy them.
- The entry point is `from mcp.server.mcpserver import MCPServer`.
- `MCPServer(name=..., version=...)` constructs it.
- `@server.tool(name=..., description=...)` registers a tool; `add_tool` and
  `remove_tool` exist for dynamic registration.
- `server.run(transport="stdio")` runs it; `run_stdio_async()` is the async
  form. `run_streamable_http_async()` and `run_sse_async()` exist for the remote
  transports, which are out of scope here.

## Scope

**In:** the local stdio transport, driven by a `docsift mcp` command.

**Out:** remote transports. Those need hosting and OAuth rather than a shared
key, and they serve claude.ai and ChatGPT's connector UI — a different audience
with a different security model. Revisit separately.

## Reuse, not reimplementation

Two existing seams make this thin, and neither requires the HTTP stack:

- `docsift.services.search_service.search_document(document_id, query, ...)`
  already searches the local SQLite store. `docsift.storage.database.init_db()`
  prepares it. This is exactly what the `docsift search` CLI command calls.
- Conversion, chunking and indexing already exist behind the API's ingest path.

**Open question for implementation:** the API's ingest runs through the job
service and its thread pool, which an MCP server does not want. Identify the
smallest synchronous function that converts, stores and indexes a file, and
extract one if it does not exist. Do not duplicate the indexing logic — a second
copy that drifts from the first is how deleted documents stay searchable.

## Tools

**`search_document(path, query, limit=5, max_tokens=2000, context=0)`**

The tool that earns its place. Takes a path to a local file, ensures it is
converted and indexed (cached, so repeat calls are free), searches it, and
returns only the matching chunks with their page and section metadata.

This is the whole product in one call: the agent sends a question and gets back
a few hundred tokens instead of a whole document.

**`convert_document(path, engine="auto")`**

Converts and indexes a file, returning a summary — document id, page count,
estimated tokens, chunk count — **not the Markdown**. Returning the full
Markdown would push the entire document into the model's context and undo the
reason DocSift exists. A separate `get_document_markdown` may be added later for
callers who genuinely want it, with the cost stated in its description.

Tool descriptions are part of the interface: a model chooses tools by reading
them. Say when to prefer search over retrieval, in the same spirit as the
connector operation descriptions written for M6.

## Requirements

- **MCP-1.** A `mcp` optional extra. Installing DocSift without it must be
  unaffected, and `docsift mcp` must fail with a clear install hint rather than
  an ImportError traceback — the same treatment engines already get.
- **MCP-2.** The import stays lazy. No module-level `import mcp` anywhere on a
  path the CLI or API touches.
- **MCP-3.** The full test suite must pass with the `mcp` extra absent. This is
  the existing CI parity rule; tests for this feature skip cleanly when the SDK
  is not installed.
- **MCP-4.** Tool errors must not surface document content, matching the
  content-leak guard the engines observe. An exception type, not its text.
- **MCP-5.** Paths are validated before use. A tool argument is attacker-adjacent
  input the moment an agent is summarising untrusted text, so path traversal and
  absolute-path handling need the same care the artifact store already applies.
- **MCP-6.** Documented in the README with a copy-pasteable client config block,
  since the failure mode for MCP is a user who cannot get the server registered.

## Acceptance

- `docsift mcp` starts, and a real MCP client lists both tools.
- `search_document` against a local PDF returns chunks whose text matches what
  `docsift search` returns for the same query.
- Uninstalling the `mcp` extra breaks nothing else: full suite still green.
- A first call converts; a second call on the same file hits the cache and
  returns without reconverting.
