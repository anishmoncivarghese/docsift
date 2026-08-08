"""DocSift as a local MCP server, spoken over stdio.

Runs on the user's own machine and calls the library in process: no service, no
network, no hosting. That makes "documents never leave this machine" a property
of how the server runs rather than a deployment recommendation.

The tool bodies (`search_local`, `convert_local`) deliberately hold all the
logic and need no MCP SDK, so they stay testable when the `mcp` extra is absent.
Only `build_server` imports the SDK.
"""

from pathlib import Path
from typing import Any

from docsift import __version__
from docsift.core.exceptions import DocSiftError

# Kept in sync with the CLI's own defaults so the two surfaces agree.
DEFAULT_LIMIT = 5
DEFAULT_MAX_TOKENS = 2000
DEFAULT_CONTEXT = 0


def sdk_available() -> bool:
    """Whether the `mcp` extra is installed.

    The SDK is imported lazily inside `build_server`, so importing this module
    succeeds without it. Callers that need to fail with a helpful message --
    rather than an ImportError traceback from deep inside a server start -- ask
    here first, the same way engines expose `is_available`.
    """
    from importlib import util

    try:
        return util.find_spec("mcp") is not None
    except (ImportError, ValueError):
        return False


def _resolve_path(raw: str) -> Path:
    """Validate a caller-supplied path.

    A tool argument is attacker-adjacent the moment an agent is summarising
    untrusted text, so this rejects anything that is not an existing regular
    file before it reaches an engine. It deliberately does *not* confine paths
    to a root: a local MCP server exists to read the user's own files, and it
    has exactly the filesystem access of the user who started it.
    """
    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"path not found: {raw}") from exc
    if not path.is_file():
        raise ValueError(f"not a regular file: {raw}")
    return path


def _safe(operation: str, func, *args, **kwargs):
    """Run `func`, converting anything unexpected into a content-safe error.

    DocSift's own errors are content-safe by construction. Anything else may
    quote document content in its message, so only the type name escapes --
    the same guard the engine adapters apply.
    """
    try:
        return func(*args, **kwargs)
    except (DocSiftError, ValueError):
        raise
    except Exception as exc:
        raise RuntimeError(f"{operation} failed: {type(exc).__name__}") from exc


def ensure_indexed(path: Path) -> str:
    """Return the document id for `path`, converting and indexing it if needed.

    Conversion is content-addressed, so a file already ingested -- under any
    name -- is recognised and not converted again.
    """
    from docsift.services.ingest_service import document_id_for_file, ingest_document
    from docsift.storage import database

    database.init_db()
    document_id = document_id_for_file(path)
    if database.get_document(document_id) is not None:
        return document_id
    return ingest_document(path).document_id


def convert_local(path: str, engine: str = "auto") -> dict[str, Any]:
    """Convert and index a local file, returning a summary rather than the text.

    Returning the Markdown here would push the whole document into the model's
    context and undo the reason DocSift exists.
    """
    resolved = _resolve_path(path)

    def run() -> dict[str, Any]:
        from docsift.services.ingest_service import document_id_for_file, ingest_document
        from docsift.storage import database

        database.init_db()
        document_id = document_id_for_file(resolved)
        existing = database.get_document(document_id)
        if existing is not None:
            return {"document_id": document_id, "already_indexed": True}
        result = ingest_document(resolved, engine=engine)
        return {
            "document_id": result.document_id,
            "already_indexed": False,
            "engine": result.conversion.engine,
            "pages": result.document.page_count,
            "estimated_tokens": result.metrics.estimated_tokens,
            "chunks": len(result.chunks),
            "warnings": [warning.code for warning in result.warnings],
        }

    return _safe("conversion", run)


def search_local(
    path: str,
    query: str,
    limit: int = DEFAULT_LIMIT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    context: int = DEFAULT_CONTEXT,
) -> dict[str, Any]:
    """Search a local document, returning only the chunks that match."""
    resolved = _resolve_path(path)

    def run() -> dict[str, Any]:
        from docsift.services.search_service import search_document

        document_id = ensure_indexed(resolved)
        response = search_document(
            document_id,
            query,
            limit=limit,
            max_tokens=max_tokens,
            context=context,
        )
        return response.model_dump(mode="json")

    return _safe("search", run)


SEARCH_DESCRIPTION = """\
Answer a question about a local document without reading the whole thing.

Converts the file if it has not been seen before (cached afterwards, so repeat
calls are cheap), then returns only the passages matching the query, each with
its page numbers and section heading for citation.

Prefer this over converting and reading a document in full: it is what keeps a
long PDF from consuming the context window. Search is lexical, so use words that
would literally appear in the text rather than paraphrases."""

CONVERT_DESCRIPTION = """\
Convert a local document (PDF, Word, PowerPoint, Excel, HTML, CSV, ...) to
Markdown and index it for searching.

Returns a summary -- document id, page count, token estimate, chunk count -- not
the text itself, because a whole document does not belong in the context window.
Use search_document to get the parts that answer a question."""


def build_server():
    """Construct the MCP server. Requires the `mcp` extra."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(name="docsift", version=__version__)

    @server.tool(name="search_document", description=SEARCH_DESCRIPTION)
    def search_document_tool(
        path: str,
        query: str,
        limit: int = DEFAULT_LIMIT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        context: int = DEFAULT_CONTEXT,
    ) -> dict[str, Any]:
        return search_local(path, query, limit=limit, max_tokens=max_tokens, context=context)

    @server.tool(name="convert_document", description=CONVERT_DESCRIPTION)
    def convert_document_tool(path: str, engine: str = "auto") -> dict[str, Any]:
        return convert_local(path, engine=engine)

    return server


def run_stdio() -> None:
    """Serve over stdio.

    stdout is the protocol channel: anything else written there corrupts the
    session, which is why the CLI command prints nothing on success.
    """
    build_server().run(transport="stdio")
