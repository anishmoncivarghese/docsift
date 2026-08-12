"""What a chunk from a deck can actually be cited as."""

from pathlib import Path

import pytest

pytest.importorskip("markitdown")

from docsift.services.conversion_service import convert_document  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"
NEEDLE = "Vendor dependency remains unresolved in the APAC corridor"


def _convert(tmp_path):
    return convert_document(FIXTURES / "deck.pptx", output_dir=tmp_path, use_cache=False)


def test_every_chunk_knows_which_slide_it_came_from(tmp_path):
    result = _convert(tmp_path)
    assert result.chunks, "the deck produced no chunks"
    assert all(chunk.pages for chunk in result.chunks), (
        "chunks without slide attribution: "
        f"{[c.chunk_id for c in result.chunks if not c.pages][:5]}"
    )


def test_slide_numbers_do_not_go_backwards(tmp_path):
    result = _convert(tmp_path)
    firsts = [chunk.pages[0] for chunk in result.chunks]
    assert firsts == sorted(firsts), firsts


def test_a_phrase_on_slide_14_is_cited_as_slide_14(tmp_path):
    result = _convert(tmp_path)
    hits = [chunk for chunk in result.chunks if NEEDLE in chunk.text]
    assert len(hits) == 1, f"expected one chunk to contain the needle, got {len(hits)}"
    assert hits[0].pages == [14], hits[0].pages


def test_chunks_carry_the_slide_title(tmp_path):
    result = _convert(tmp_path)
    hits = [chunk for chunk in result.chunks if NEEDLE in chunk.text]
    assert hits[0].section_path, "no section path"
    assert "Section 14" in hits[0].section_path


def test_markers_do_not_leak_into_chunk_text(tmp_path):
    result = _convert(tmp_path)
    for chunk in result.chunks:
        assert "Slide number" not in chunk.text
        assert "<!-- page:" not in chunk.text


def test_page_count_is_the_slide_count(tmp_path):
    assert _convert(tmp_path).document.page_count == 60
