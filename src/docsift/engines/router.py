from pathlib import Path

from docsift.core.exceptions import EngineNotAvailableError, UnsupportedFileError

DOCLING_SUFFIXES: set[str] = {".pdf"}
MARKITDOWN_SUFFIXES: set[str] = {
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".xml",
    ".zip",
    ".epub",
    ".txt",
    ".md",
}
SUPPORTED_SUFFIXES: set[str] = DOCLING_SUFFIXES | MARKITDOWN_SUFFIXES
VALID_ENGINE_CHOICES: set[str] = {"auto", "docling", "markitdown"}


def select_engine_name(path: Path, requested: str = "auto") -> tuple[str, str]:
    """Pick an engine for `path`. Returns (engine_name, human-readable reason)."""
    if requested not in VALID_ENGINE_CHOICES:
        raise EngineNotAvailableError(
            f"unknown engine '{requested}'; expected one of {sorted(VALID_ENGINE_CHOICES)}"
        )
    if requested != "auto":
        return requested, "explicit user selection"
    suffix = path.suffix.lower()
    if suffix in DOCLING_SUFFIXES:
        return "docling", "PDF always routes to Docling"
    if suffix in MARKITDOWN_SUFFIXES:
        return "markitdown", f"'{suffix}' routes to MarkItDown"
    raise UnsupportedFileError(
        f"unsupported file type '{suffix}'; supported: {sorted(SUPPORTED_SUFFIXES)}"
    )
