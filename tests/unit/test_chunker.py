from docsift.core.options import ChunkOptions
from docsift.processing.chunker import chunk_markdown

PARA = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod. "
DOC = (
    "# Report\n\n"
    "<!-- page: 1 -->\n\n"
    "## Revenue\n\n" + (PARA * 12) + "\n\n" + (PARA * 12) + "\n\n"
    "<!-- page: 2 -->\n\n"
    "## Expenses\n\n" + (PARA * 12) + "\n\n"
    "| Quarter | Value |\n|---|---|\n| Q1 | 100 |\n| Q2 | 120 |\n\n"
    "## Risks\n\n" + (PARA * 3) + "\n"
)
SMALL = ChunkOptions(max_tokens=250, overlap_tokens=40)


def test_chunks_respect_token_budget():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert chunk.estimated_tokens <= SMALL.max_tokens + SMALL.overlap_tokens


def test_no_chunk_ends_with_a_heading():
    for chunk in chunk_markdown(DOC, "doc_abc", SMALL):
        last_line = chunk.text.strip().splitlines()[-1]
        assert not last_line.startswith("#")


def test_stable_ids_and_prefix():
    first = [c.chunk_id for c in chunk_markdown(DOC, "doc_abc", SMALL)]
    second = [c.chunk_id for c in chunk_markdown(DOC, "doc_abc", SMALL)]
    assert first == second
    assert first[0] == "doc_abc_c000"


def test_section_paths_follow_headings():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    assert any(chunk.section_path == ["Report", "Revenue"] for chunk in chunks)
    assert any(chunk.section_path == ["Report", "Expenses"] for chunk in chunks)


def test_pages_tracked_from_markers():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    assert any(2 in chunk.pages for chunk in chunks)
    assert all("<!-- page:" not in chunk.text for chunk in chunks)


def test_small_table_stays_intact():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    holders = [c for c in chunks if "| Q1 | 100 |" in c.text]
    assert len(holders) == 1
    assert "| Quarter | Value |" in holders[0].text


def test_oversized_table_splits_with_repeated_header():
    rows = "\n".join(f"| row-{i} | {'x' * 60} |" for i in range(80))
    table_doc = f"# T\n\n| K | V |\n|---|---|\n{rows}\n"
    chunks = chunk_markdown(table_doc, "doc_t", ChunkOptions(max_tokens=300, overlap_tokens=0))
    table_chunks = [c for c in chunks if "| row-" in c.text]
    assert len(table_chunks) >= 2
    for chunk in table_chunks:
        assert "| K | V |" in chunk.text


def test_overlap_carries_previous_tail():
    chunks = chunk_markdown(DOC, "doc_abc", SMALL)
    assert len(chunks) >= 2
    prev_tail = chunks[0].text.strip().splitlines()[-1]
    assert prev_tail in chunks[1].text


def test_empty_markdown_yields_no_chunks():
    assert chunk_markdown("", "doc_e") == []


def test_trailing_heading_without_body_is_preserved():
    doc = "# Title\n\nIntro paragraph with enough words to matter here.\n\n## Appendix\n"
    chunks = chunk_markdown(doc, "doc_x")
    assert chunks
    assert any("## Appendix" in chunk.text for chunk in chunks)


def test_headings_only_document_is_preserved():
    chunks = chunk_markdown("# A\n\n## B\n\n### C\n", "doc_h")
    assert chunks
    joined = "\n".join(chunk.text for chunk in chunks)
    assert "# A" in joined
    assert "## B" in joined
    assert "### C" in joined


def test_budget_exceeded_only_by_an_indivisible_block():
    for chunk in chunk_markdown(DOC, "doc_abc", SMALL):
        if chunk.estimated_tokens > SMALL.max_tokens + SMALL.overlap_tokens:
            body_blocks = [
                block
                for block in chunk.text.split("\n\n")
                if block.strip() and not block.strip().startswith("#")
            ]
            assert len(body_blocks) <= 1, chunk.text


def test_section_path_reports_deepest_context():
    doc = "# H1\n\n## H2\n\n### H3\n\nparagraph body text\n"
    chunks = chunk_markdown(doc, "doc_n")
    assert chunks
    assert chunks[-1].section_path == ["H1", "H2", "H3"]


FENCED_DOC = (
    "# Guide\n\n"
    "Intro paragraph about the setup process here.\n\n"
    "```python\n"
    "# Setup step\n"
    "import os\n"
    "| not | a | table |\n"
    "```\n\n"
    "Closing paragraph after the code block.\n"
)


def test_fence_comments_are_not_headings():
    chunks = chunk_markdown(FENCED_DOC, "doc_f")
    for chunk in chunks:
        assert "Setup step" not in chunk.section_path


def test_fenced_block_stays_in_one_chunk():
    chunks = chunk_markdown(FENCED_DOC, "doc_f", ChunkOptions(max_tokens=40, overlap_tokens=0))
    holders = [c for c in chunks if "import os" in c.text]
    assert len(holders) == 1
    assert holders[0].text.count("```") == 2


def test_fenced_pipe_line_is_not_treated_as_a_table():
    chunks = chunk_markdown(FENCED_DOC, "doc_f")
    holder = next(c for c in chunks if "| not | a | table |" in c.text)
    assert "import os" in holder.text


def test_two_line_table_keeps_both_rows():
    from docsift.processing.chunker import _split_table

    rows = ["| K | V |", "| a | b |"]
    parts = _split_table(rows, 1000)
    assert parts == [rows]
