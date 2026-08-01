"""Generate binary test fixtures. Run: uv run python scripts/make_fixtures.py"""

from pathlib import Path

from fpdf import FPDF

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def make_sample() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=16)
    pdf.cell(text="Hello DocSift")
    pdf.ln(12)
    pdf.set_font("helvetica", size=12)
    pdf.cell(text="This one-page PDF exercises the Docling engine.")
    pdf.output(str(FIXTURES / "sample.pdf"))


def make_table() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(text="Quarterly results")
    pdf.ln(10)
    with pdf.table() as table:
        for row_data in (
            ("Quarter", "Revenue", "Costs"),
            ("Q1", "100", "60"),
            ("Q2", "120", "70"),
        ):
            row = table.row()
            for cell in row_data:
                row.cell(cell)
    pdf.output(str(FIXTURES / "table.pdf"))


def make_multipage() -> None:
    pdf = FPDF()
    pdf.set_font("helvetica", size=12)
    for page in range(1, 4):
        pdf.add_page()
        pdf.cell(text=f"Page {page} of the multipage DocSift fixture.")
    pdf.output(str(FIXTURES / "multipage.pdf"))


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    make_sample()
    make_table()
    make_multipage()
    print(f"wrote fixtures to {FIXTURES}")


if __name__ == "__main__":
    main()
