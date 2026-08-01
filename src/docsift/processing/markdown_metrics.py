import re

_HEADING = re.compile(r"^#{1,6} ", re.MULTILINE)


def count_headings(markdown: str) -> int:
    """Number of ATX headings (lines starting with 1-6 '#' plus a space)."""
    return len(_HEADING.findall(markdown))


def count_tables(markdown: str) -> int:
    """Number of table blocks: maximal runs of consecutive lines starting with '|'."""
    tables = 0
    in_table = False
    for line in markdown.splitlines():
        is_row = line.lstrip().startswith("|")
        if is_row and not in_table:
            tables += 1
        in_table = is_row
    return tables
