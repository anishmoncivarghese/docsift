"""Regenerate `scanned.pdf`, the fixture that forces docling down the OCR path.

Run with `uv run python tests/fixtures/make_scanned.py`. The output is committed;
this exists so the fixture can be explained and rebuilt, not built on the fly.

Why it has to be an image: a born-digital PDF has a text layer, so docling never
starts its OCR model and never produces the per-page logging that buried the
progress output in 0.5.2. `multipage.pdf` is born-digital, which is exactly why
CI stayed green while a real document wrote 113 lines to stderr.
"""

from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent

LINES = [
    "Quarterly Operations Review",
    "",
    "Freight costs rose 12 percent over the period, driven",
    "mainly by fuel prices and port handling delays.",
    "",
    "Headcount was unchanged. Two sites reported",
    "equipment downtime exceeding the agreed threshold.",
]


def main() -> None:
    # Text drawn as pixels, not as a text layer, so docling has to OCR it --
    # which is the whole point of the fixture.
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=44)
    except TypeError:  # Pillow < 10.1 cannot scale the default font
        font = ImageFont.load_default()

    y = 160
    for line in LINES:
        draw.text((140, y), line, fill=(20, 20, 20), font=font)
        y += 90

    png = HERE / "_scanned_page.png"
    image.save(png)

    try:
        pdf = FPDF(unit="pt", format=(612, 792))
        for _ in range(2):
            pdf.add_page()
            pdf.image(str(png), x=0, y=0, w=612, h=792)
        pdf.output(str(HERE / "scanned.pdf"))
    finally:
        png.unlink(missing_ok=True)

    print("wrote", HERE / "scanned.pdf")


if __name__ == "__main__":
    main()
