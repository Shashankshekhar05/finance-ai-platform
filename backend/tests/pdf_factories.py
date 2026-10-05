"""Deterministic PDF fixtures built with PyMuPDF (no binary blobs in git).

find_tables needs ruling lines AND cell text to fire — grid pages always
include both. Image pages embed a generated PNG (raster → get_images).
"""

import fitz

PROSE = (
    "Management discussion and analysis of financial condition. Revenue grew "
    "across all segments this fiscal year. Operating margins expanded. "
)


def _grid(page: fitz.Page) -> None:
    x0, y0, x1, y1 = 72, 72, 400, 200
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(x0, y0, x1, y1))
    for i in (1, 2):
        yy = y0 + (y1 - y0) * i / 3
        shape.draw_line(fitz.Point(x0, yy), fitz.Point(x1, yy))
    for i in (1, 2):
        xx = x0 + (x1 - x0) * i / 3
        shape.draw_line(fitz.Point(xx, y0), fitz.Point(xx, y1))
    shape.finish(width=1)
    shape.commit()


def _cell_text(page: fitz.Page) -> None:
    page.insert_text((80, 100), "Revenue 100")
    page.insert_text((200, 100), "Cost 40")
    page.insert_text((80, 140), "Profit 60")


def text_pdf(pages: int = 2) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), PROSE * 4)
    return doc.tobytes()


def table_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    _grid(page)
    _cell_text(page)
    return doc.tobytes()


def image_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20))
    page.insert_image(fitz.Rect(72, 72, 200, 200), stream=pix.tobytes("png"))
    return doc.tobytes()


def mixed_pdf() -> bytes:
    """Page 1: long prose + ruled table (mixed). Page 2: prose (narrative)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 500), PROSE * 6)
    _grid(page)
    _cell_text(page)
    doc.new_page().insert_text((72, 72), PROSE * 4)
    return doc.tobytes()


def empty_pages_pdf(pages: int) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    return doc.tobytes()


def non_pdf_bytes() -> bytes:
    return b"definitely not a pdf, just plain text"


def truncated_pdf_bytes() -> bytes:
    return b"%PDF-1.4 truncated before any object"
