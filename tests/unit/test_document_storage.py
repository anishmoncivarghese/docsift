from datetime import UTC, datetime

import pytest

from docsift.core.exceptions import UnsupportedFileError
from docsift.core.models import (
    ConversionMetadata,
    ConversionMetrics,
    ConversionResult,
    DocumentContent,
    SourceMetadata,
)
from docsift.storage import documents


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))


# Fixed rather than `datetime.now(UTC)`: `_result()` is called twice per
# round-trip test (once to store, once to build the expected value), and two
# independent `now()` calls essentially never land on the same microsecond.
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _result(document_id: str = "doc_abc123def456") -> ConversionResult:
    now = _NOW
    return ConversionResult(
        document_id=document_id,
        source=SourceMetadata(
            filename="report.pdf",
            media_type="application/pdf",
            size_bytes=10,
            sha256="a" * 64,
        ),
        conversion=ConversionMetadata(
            engine="markitdown",
            engine_version="1.0",
            docsift_version="0.1.1",
            selection_reason="test",
            started_at=now,
            completed_at=now,
            duration_ms=1,
        ),
        document=DocumentContent(markdown="# Title\n\nBody.\n"),
        metrics=ConversionMetrics(characters=16, words=3, estimated_tokens=5),
    )


def test_store_and_load_round_trip():
    stored = documents.store_result(_result())
    assert stored.name == "result.json"
    loaded = documents.load_result("doc_abc123def456")
    assert loaded == _result()


def test_markdown_is_written_alongside_the_result():
    documents.store_result(_result())
    markdown = documents.document_dir("doc_abc123def456") / "document.md"
    assert markdown.read_text(encoding="utf-8") == "# Title\n\nBody.\n"


def test_load_returns_none_for_unknown_document():
    assert documents.load_result("doc_000000000000") is None


def test_load_returns_none_for_corrupt_result():
    documents.store_result(_result())
    (documents.document_dir("doc_abc123def456") / "result.json").write_text(
        "{not json", encoding="utf-8"
    )
    assert documents.load_result("doc_abc123def456") is None


def test_delete_removes_everything():
    documents.store_result(_result())
    assert documents.delete_document_files("doc_abc123def456") is True
    assert not documents.document_dir("doc_abc123def456").exists()
    assert documents.delete_document_files("doc_abc123def456") is False


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../etc",
        "doc_../../etc",
        "doc_ABC123DEF456",
        "doc_abc",
        "doc_abc123def456/x",
        "",
        "doc_abc123def45g",
    ],
)
def test_malformed_document_ids_are_rejected(bad_id):
    with pytest.raises(UnsupportedFileError, match="invalid document id"):
        documents.document_dir(bad_id)
