from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from docsift import __version__
from docsift.core.exceptions import DocSiftError
from docsift.core.models import ComparisonResult, EngineRunSummary
from docsift.processing.markdown_metrics import count_headings, count_tables
from docsift.services.comparison_report import render_report
from docsift.services.conversion_service import build_source_metadata, convert_document

DEFAULT_ENGINES: tuple[str, ...] = ("docling", "markitdown")


def _run_engine(path: Path, engine: str, output_dir: Path | None) -> EngineRunSummary:
    try:
        result = convert_document(path, engine=engine, output_dir=output_dir)
    except DocSiftError as exc:
        return EngineRunSummary(engine=engine, success=False, error=str(exc))
    except Exception as exc:  # never leak content; expose only the type name
        return EngineRunSummary(engine=engine, success=False, error=type(exc).__name__)
    markdown = result.document.markdown
    return EngineRunSummary(
        engine=engine,
        success=True,
        engine_version=result.conversion.engine_version,
        duration_ms=result.conversion.duration_ms,
        characters=result.metrics.characters,
        words=result.metrics.words,
        estimated_tokens=result.metrics.estimated_tokens,
        heading_count=count_headings(markdown),
        table_count=count_tables(markdown),
        warning_count=len(result.warnings),
        ocr_used=result.conversion.ocr_used,
        markdown_path=str(output_dir / f"{path.stem}.md") if output_dir else None,
        result_json_path=str(output_dir / f"{path.stem}.docsift.json") if output_dir else None,
    )


def compare_document(
    path: Path,
    output_dir: Path | None = None,
    engines: Sequence[str] = DEFAULT_ENGINES,
) -> ComparisonResult:
    """Run every engine on `path`; one engine's failure never stops the others."""
    path = Path(path)
    source = build_source_metadata(path)  # raises for inputs no engine could handle

    runs = [
        _run_engine(path, engine, (Path(output_dir) / engine) if output_dir else None)
        for engine in engines
    ]
    comparison = ComparisonResult(
        source=source,
        docsift_version=__version__,
        created_at=datetime.now(UTC),
        runs=runs,
    )
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{path.stem}.compare.json").write_text(
            comparison.model_dump_json(indent=2), encoding="utf-8"
        )
        (output_dir / f"{path.stem}.compare.md").write_text(
            render_report(comparison), encoding="utf-8"
        )
    return comparison
