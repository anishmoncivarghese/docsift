"""Generate binary test fixtures. Run: uv run python scripts/make_fixtures.py"""

from pathlib import Path

from fpdf import FPDF


def main() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=16)
    pdf.cell(text="Hello DocSift")
    pdf.ln(12)
    pdf.set_font("helvetica", size=12)
    pdf.cell(text="This one-page PDF exercises the Docling engine.")
    out = Path(__file__).parent.parent / "tests" / "fixtures" / "sample.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
