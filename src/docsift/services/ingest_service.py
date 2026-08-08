"""Persisting a converted document: artifacts, search index, document row.

The API reaches this through the job service's worker thread; the MCP server
calls it synchronously. Both go through `store_and_index` so the ordering
guarantee below is stated once. A second copy of this sequence that drifted from
the first is how a deleted document could stay searchable.
"""

import hashlib
from pathlib import Path

from docsift.core.models import ConversionResult
from docsift.core.options import ConversionOptions
from docsift.storage import database, documents


def document_id_for_file(path: Path) -> str:
    """The content-addressed id a conversion of `path` will produce.

    Lets a caller check whether a file is already stored without converting it.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"doc_{digest.hexdigest()[:12]}"


def store_and_index(result: ConversionResult) -> Path:
    """Persist `result` and return the path its artifacts were written to.

    Search is part of the completed-document contract from Milestone 5. The
    index is replaced before the document row is published, so a caller can
    never observe a successful-but-unsearchable conversion. The index operation
    is atomic per document.
    """
    result_path = documents.store_result(result)
    database.index_document_chunks(result.document_id, result.chunks)
    database.save_document(
        document_id=result.document_id,
        filename=result.source.filename,
        media_type=result.source.media_type,
        size_bytes=result.source.size_bytes,
        sha256=result.source.sha256,
        engine=result.conversion.engine,
        result_path=str(result_path),
    )
    return result_path


def ingest_document(
    path: Path,
    engine: str = "auto",
    options: ConversionOptions | None = None,
) -> ConversionResult:
    """Convert `path` and persist it, returning the conversion result.

    The straight-line synchronous form. The API does not use this because it
    has to check for a cancelling DELETE between conversion and storage.
    """
    from docsift.services.conversion_service import convert_document

    result = convert_document(path, engine=engine, options=options)
    store_and_index(result)
    return result
