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
from docsift.core.options import ConversionOptions
from docsift.engines.registry import get_engine
from docsift.engines.router import SUPPORTED_SUFFIXES, select_engine_name
from docsift.processing.chunker import chunk_markdown
from docsift.processing.cleaner import build_clean_plan, clean_excerpt, clean_markdown
from docsift.processing.token_estimator import estimate_tokens
from docsift.storage.cache import cache_key, load_cached, store_cached

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


def _write_artifacts(result: ConversionResult, path: Path, output_dir: Path | None) -> None:
    if output_dir is None:
        return
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{path.stem}.md").write_text(result.document.markdown, encoding="utf-8")
    (output_dir / f"{path.stem}.docsift.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )


def convert_document(
    path: Path,
    engine: str = "auto",
    output_dir: Path | None = None,
    options: ConversionOptions | None = None,
    use_cache: bool = True,
) -> ConversionResult:
    options = options or ConversionOptions()
    path = Path(path)
    _validate(path)
    engine_name, reason = select_engine_name(path, engine)
    engine_impl = get_engine(engine_name)
    source = build_source_metadata(path)

    key = cache_key(source.sha256, engine_name, engine_impl.version(), __version__, options)
    if use_cache:
        cached = load_cached(key)
        if cached is not None:
            cached = cached.model_copy(deep=True)
            cached.conversion.cached = True
            # The cache key is content-addressed (source sha256), not path- or
            # filename-addressed, so a byte-identical file under a different
            # name/path hits the same entry. filename/media_type and the
            # engine-selection reason aren't derived from file content, so they
            # must reflect *this* request, not whichever file populated the
            # cache first. duration_ms intentionally stays the original run's
            # value — it describes how long the actual conversion took.
            cached.source = source
            cached.conversion.selection_reason = reason
            _write_artifacts(cached, path, output_dir)
            return cached

    started = datetime.now(UTC)
    try:
        output = engine_impl.convert(path, options)
    except DocSiftError:
        raise
    except Exception as exc:  # engine bugs must surface as structured errors
        # Exception text can quote document content; expose only the type name.
        raise ConversionFailedError(
            f"{engine_name} failed on '{path.name}': {type(exc).__name__}"
        ) from exc
    completed = datetime.now(UTC)

    raw_markdown = output.markdown
    clean_plan = build_clean_plan(raw_markdown, options.clean)
    markdown, clean_stats = clean_markdown(raw_markdown, options.clean, plan=clean_plan)
    document_id = f"doc_{source.sha256[:12]}"

    if output.chunks is not None:
        # Engine-supplied chunks are built from the engine's own structured
        # document and never pass through the document-level cleaner, so apply
        # the same decisions here or they would keep the furniture the Markdown
        # just lost. A chunk that is nothing but furniture is dropped.
        chunks = []
        for chunk in output.chunks:
            text, _ = clean_excerpt(chunk.text, clean_plan)
            if not text.strip():
                continue
            chunks.append(
                chunk.model_copy(
                    update={
                        "chunk_id": f"{document_id}_{chunk.chunk_id}",
                        "text": text,
                        "estimated_tokens": estimate_tokens(text),
                    }
                )
            )
    else:
        chunks = chunk_markdown(markdown, document_id, options.chunk)

    warnings = list(output.warnings)
    if not markdown.strip():
        warnings.append(
            ConversionWarning(
                code="empty_output",
                message=f"{engine_name} produced no Markdown for '{path.name}'",
            )
        )
    if clean_stats.furniture_lines_removed > 0:
        warnings.append(
            ConversionWarning(
                code="furniture_removed",
                message=(
                    f"removed {clean_stats.furniture_lines_removed} repeated header/footer lines"
                ),
            )
        )
    if output.chunks and not chunks:
        warnings.append(
            ConversionWarning(
                code="all_chunks_empty_after_cleaning",
                message=f"cleaning emptied every chunk supplied by {engine_name}",
            )
        )
    if output.chunks is not None and options.chunk.overlap_tokens > 0:
        warnings.append(
            ConversionWarning(
                code="overlap_not_supported",
                message=f"--overlap has no effect on chunks supplied by {engine_name}",
            )
        )
    result = ConversionResult(
        document_id=document_id,
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
        chunks=chunks,
        metrics=ConversionMetrics(
            characters=len(markdown),
            words=len(markdown.split()),
            estimated_tokens=estimate_tokens(markdown),
            raw_estimated_tokens=estimate_tokens(raw_markdown),
            duplicate_lines_removed=(
                clean_stats.duplicate_lines_removed + clean_stats.furniture_lines_removed
            ),
        ),
        warnings=warnings,
    )

    if use_cache:
        store_cached(key, result)
    _write_artifacts(result, path, output_dir)
    return result
