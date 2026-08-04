import os
import re
import shutil
import tempfile
from pathlib import Path

from docsift.core.config import get_settings
from docsift.core.exceptions import UnsupportedFileError
from docsift.core.models import ConversionResult

_DOCUMENT_ID = re.compile(r"^doc_[0-9a-f]{12}$")


def document_dir(document_id: str) -> Path:
    """Directory holding one document's artifacts.

    The id is validated against DocSift's own `doc_{12 hex}` shape rather than
    sanitized, so a client-supplied value can never traverse out of the data
    directory (NFR-04).

    This does not create the directory. Task 6 calls this for every HTTP
    lookup by id (GET/DELETE), including ids that don't exist yet — a
    read-only path helper must not leave empty directories behind just
    because someone looked up an id.
    """
    if not _DOCUMENT_ID.fullmatch(document_id):
        raise UnsupportedFileError(f"invalid document id: {document_id!r}")
    return get_settings().data_dir / "documents" / document_id


def _write_atomic(path: Path, text: str) -> None:
    handle = tempfile.NamedTemporaryFile(
        "w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8"
    )
    try:
        handle.write(text)
        handle.close()
        os.replace(handle.name, path)
    except OSError:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise


def store_result(result: ConversionResult) -> Path:
    """Persist a conversion result and its Markdown. Returns the result.json path."""
    directory = document_dir(result.document_id)
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / "result.json"
    _write_atomic(directory / "document.md", result.document.markdown)
    _write_atomic(result_path, result.model_dump_json(indent=2))
    return result_path


def load_result(document_id: str) -> ConversionResult | None:
    """Stored result, or None when absent or unreadable."""
    result_path = document_dir(document_id) / "result.json"
    if not result_path.is_file():
        return None
    try:
        return ConversionResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def delete_document_files(document_id: str) -> bool:
    """Remove a document's artifact directory. True if anything existed."""
    directory = document_dir(document_id)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    return True
