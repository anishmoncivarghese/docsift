import pytest

from docsift.core.exceptions import SearchQueryError
from docsift.core.models import Chunk
from docsift.services.search_service import search_document
from docsift.storage import database


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    database.init_db()


def _index() -> str:
    document_id = "doc_abc123def456"
    database.index_document_chunks(
        document_id,
        [
            Chunk(
                chunk_id=f"{document_id}_c000",
                text="Introduction and background.",
                estimated_tokens=5,
                section_path=["Introduction"],
                pages=[1],
            ),
            Chunk(
                chunk_id=f"{document_id}_c001",
                text="Operational risk controls reduce exposure.",
                estimated_tokens=8,
                section_path=["Risk", "Operations"],
                pages=[2],
            ),
            Chunk(
                chunk_id=f"{document_id}_c002",
                text="Operational risk monitoring continues quarterly.",
                estimated_tokens=7,
                section_path=["Risk", "Monitoring"],
                pages=[3],
            ),
            Chunk(
                chunk_id=f"{document_id}_c003",
                text="Closing notes and appendix.",
                estimated_tokens=6,
                section_path=["Appendix"],
                pages=[4],
            ),
        ],
    )
    return document_id


def test_search_returns_ranked_typed_direct_matches():
    document_id = _index()

    response = search_document(document_id, "  operational   risk  ", limit=2)

    assert response.document_id == document_id
    assert response.query == "operational risk"
    assert len(response.results) == 2
    assert all(result.match for result in response.results)
    assert all(result.context_for is None for result in response.results)
    assert response.estimated_tokens == sum(r.estimated_tokens for r in response.results)
    assert response.results[0].section_path
    assert response.results[0].pages


def test_search_honors_total_token_budget_without_returning_full_document():
    document_id = _index()

    response = search_document(document_id, "operational", limit=5, max_tokens=8)

    assert len(response.results) == 1
    assert response.estimated_tokens <= 8
    assert "Introduction" not in "\n".join(result.text for result in response.results)


def test_context_expansion_includes_neighbors_and_marks_them():
    document_id = _index()

    response = search_document(document_id, '"operational risk controls"', context=1)

    assert [result.chunk_id for result in response.results] == [
        f"{document_id}_c000",
        f"{document_id}_c001",
        f"{document_id}_c002",
    ]
    assert [result.match for result in response.results] == [False, True, False]
    assert response.results[0].context_for == f"{document_id}_c001"
    assert response.results[2].context_for == f"{document_id}_c001"


def test_overlapping_context_is_deduplicated_and_direct_match_wins():
    document_id = _index()

    response = search_document(document_id, "operational", limit=2, context=1)

    ids = [result.chunk_id for result in response.results]
    assert len(ids) == len(set(ids))
    direct = {result.chunk_id for result in response.results if result.match}
    assert direct == {f"{document_id}_c001", f"{document_id}_c002"}


def test_no_matches_returns_an_empty_result_set():
    document_id = _index()

    response = search_document(document_id, "platypus")

    assert response.results == []
    assert response.estimated_tokens == 0


@pytest.mark.parametrize("query", ["", " ", "\n\t"])
def test_blank_query_is_rejected(query):
    with pytest.raises(SearchQueryError, match="query must not be blank"):
        search_document("doc_abc123def456", query)


def test_overlong_query_is_rejected_without_running_the_search():
    with pytest.raises(SearchQueryError, match="query is too long"):
        search_document("doc_abc123def456", "x" * 2000)


def test_query_with_too_many_terms_is_rejected():
    with pytest.raises(SearchQueryError, match="query has too many terms"):
        search_document("doc_abc123def456", " ".join(["term"] * 100))


def test_invalid_fts_syntax_is_hidden_behind_a_content_safe_error():
    document_id = _index()

    with pytest.raises(SearchQueryError, match="invalid search query") as error:
        search_document(document_id, '"private phrase')

    assert "private phrase" not in str(error.value)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0}, "limit must be between 1 and 20"),
        ({"limit": 21}, "limit must be between 1 and 20"),
        ({"max_tokens": 0}, "max_tokens must be between 1 and 20000"),
        ({"max_tokens": 20001}, "max_tokens must be between 1 and 20000"),
        ({"context": -1}, "context must be between 0 and 2"),
        ({"context": 3}, "context must be between 0 and 2"),
    ],
)
def test_search_controls_are_validated(kwargs, message):
    with pytest.raises(SearchQueryError, match=message):
        search_document("doc_abc123def456", "risk", **kwargs)
