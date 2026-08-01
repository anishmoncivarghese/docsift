from docsift.processing.markdown_metrics import count_headings, count_tables

DOC = """# Title

## Section one

Text with # not a heading mid-line.

|h1|h2|
|--|--|
|a|b|

More text.

| x | y |
| - | - |
| 1 | 2 |
| 3 | 4 |

### Deep heading
"""


def test_counts_headings():
    assert count_headings(DOC) == 3


def test_counts_table_blocks():
    assert count_tables(DOC) == 2


def test_empty_markdown():
    assert count_headings("") == 0
    assert count_tables("") == 0
