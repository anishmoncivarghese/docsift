from datetime import UTC, datetime

from docsift.core.models import ComparisonResult, EngineRunSummary, SourceMetadata
from docsift.services.comparison_report import render_report


def _comparison() -> ComparisonResult:
    return ComparisonResult(
        source=SourceMetadata(
            filename="report.pdf",
            media_type="application/pdf",
            size_bytes=2048,
            sha256="c" * 64,
        ),
        docsift_version="0.1.0.dev0",
        created_at=datetime.now(UTC),
        runs=[
            EngineRunSummary(
                engine="docling",
                success=True,
                engine_version="2.117.0",
                duration_ms=1500,
                characters=900,
                words=150,
                estimated_tokens=225,
                heading_count=4,
                table_count=1,
            ),
            EngineRunSummary(
                engine="markitdown",
                success=False,
                error="markitdown failed on 'report.pdf': BoomError",
            ),
        ],
    )


def test_report_contains_metric_table_and_errors():
    report = render_report(_comparison())
    assert "# Comparison: report.pdf" in report
    assert "| metric | docling | markitdown |" in report
    assert "| status | ok | failed |" in report
    assert "| estimated_tokens | 225 | — |" in report
    assert "| warning_count | 0 | — |" in report
    assert "| ocr_used | False | — |" in report
    assert "BoomError" in report
    assert "cccccccccccc" in report  # sha prefix shown
