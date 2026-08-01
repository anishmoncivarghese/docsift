from datetime import UTC, datetime

from docsift.core.models import (
    ConversionMetadata,
    ConversionMetrics,
    ConversionResult,
    DocumentContent,
    SourceMetadata,
)


def _result() -> ConversionResult:
    now = datetime.now(UTC)
    return ConversionResult(
        document_id="doc_abc123def456",
        source=SourceMetadata(
            filename="report.pdf",
            media_type="application/pdf",
            size_bytes=1234,
            sha256="a" * 64,
        ),
        conversion=ConversionMetadata(
            engine="docling",
            engine_version="2.0.0",
            docsift_version="0.1.0.dev0",
            selection_reason="PDF routes to Docling",
            started_at=now,
            completed_at=now,
            duration_ms=10,
        ),
        document=DocumentContent(markdown="# Hi"),
        metrics=ConversionMetrics(characters=4, words=2, estimated_tokens=1),
    )


def test_result_defaults():
    result = _result()
    assert result.chunks == []
    assert result.warnings == []
    assert result.conversion.ocr_used is False
    assert result.conversion.cached is False


def test_result_json_round_trip():
    result = _result()
    restored = ConversionResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_result_carries_schema_version():
    result = _result()
    assert result.schema_version == "1"
    assert '"schema_version":"1"' in result.model_dump_json().replace(" ", "")
