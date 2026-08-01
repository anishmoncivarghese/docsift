import hashlib
import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from docsift import __version__
from docsift.core.exceptions import ConversionFailedError, DocSiftError, UnsupportedFileError
from docsift.core.models import (
    ConversionMetadata,
    ConversionMetrics,
    ConversionResult,
    ConversionWarning,
    DocumentContent,
    SourceMetadata,
)
from docsift.engines.registry import get_engine
from docsift.engines.router import SUPPORTED_SUFFIXES, select_engine_name
from docsift.processing.token_estimator import estimate_tokens

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate(path: Path) -> int:
    if not path.is_file():
        raise UnsupportedFileError(f"not a file: {path}")
    size = path.stat().st_size
    if size == 0:
        raise UnsupportedFileError(f"file is empty: {path}")
    if size > MAX_FILE_SIZE_BYTES:
        raise UnsupportedFileError(
            f"file is {size} bytes; maximum is {MAX_FILE_SIZE_BYTES} (50 MB)"
        )
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileError(
            f"unsupported file type '{suffix}'; supported: {sorted(SUPPORTED_SUFFIXES)}"
        )
    return size


def build_source_metadata(path: Path) -> SourceMetadata:
    """Validate `path` and describe it. Raises UnsupportedFileError for bad inputs."""
    path = Path(path)
    size = _validate(path)
    return SourceMetadata(
        filename=path.name,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        size_bytes=size,
        sha256=_sha256(path),
    )


def convert_document(
    path: Path, engine: str = "auto", output_dir: Path | None = None
) -> ConversionResult:
    path = Path(path)
    _validate(path)
    engine_name, reason = select_engine_name(path, engine)
    engine_impl = get_engine(engine_name)
    source = build_source_metadata(path)

    started = datetime.now(UTC)
    try:
        output = engine_impl.convert(path)
    except DocSiftError:
        raise
    except Exception as exc:  # engine bugs must surface as structured errors
        # Exception text can quote document content; expose only the type name.
        raise ConversionFailedError(
            f"{engine_name} failed on '{path.name}': {type(exc).__name__}"
        ) from exc
    completed = datetime.now(UTC)

    markdown = output.markdown
    warnings = list(output.warnings)
    if not markdown.strip():
        warnings.append(
            ConversionWarning(
                code="empty_output",
                message=f"{engine_name} produced no Markdown for '{path.name}'",
            )
        )
    result = ConversionResult(
        document_id=f"doc_{source.sha256[:12]}",
        source=source,
        conversion=ConversionMetadata(
            engine=engine_name,
            engine_version=output.engine_version,
            docsift_version=__version__,
            selection_reason=reason,
            started_at=started,
            completed_at=completed,
            duration_ms=int((completed - started).total_seconds() * 1000),
            ocr_used=output.ocr_used,
        ),
        document=DocumentContent(
            title=output.title,
            page_count=output.page_count,
            markdown=markdown,
        ),
        metrics=ConversionMetrics(
            characters=len(markdown),
            words=len(markdown.split()),
            estimated_tokens=estimate_tokens(markdown),
        ),
        warnings=warnings,
    )

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{path.stem}.md").write_text(markdown, encoding="utf-8")
        (output_dir / f"{path.stem}.docsift.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
    return result
