from pathlib import Path

import pytest

pytest.importorskip("docling")
pytest.importorskip("markitdown")

from docsift.services.comparison_service import compare_document  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"

pytestmark = pytest.mark.integration


def test_compare_table_pdf_with_real_engines(tmp_path):
    comparison = compare_document(FIXTURES / "table.pdf", output_dir=tmp_path)
    by_engine = {run.engine: run for run in comparison.runs}
    assert by_engine["docling"].success is True
    assert by_engine["markitdown"].success is True
    assert by_engine["docling"].table_count >= 1
    assert (tmp_path / "table.compare.json").exists()
    assert (tmp_path / "table.compare.md").exists()
