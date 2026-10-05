"""PDF parsing: validation, page extraction, page classification.

PyMuPDF ONLY (page count, text, raster-image detection, AND table
detection via find_tables) — no second PDF library: nothing here needs
what PyMuPDF lacks. Full table cell serialization is a chunking-phase
concern, not this phase's.

Pure functions over bytes: no database, no HTTP, no side effects.
Same bytes → same payloads (deterministic), unit-testable in isolation.

Classification rule (documented, deterministic):
- table-only signal (tables, <50 text chars, no images) → "table"
- image-only signal (images, <50 text chars, no tables) → "visual"
- neither signal (prose or empty page) → "narrative"
- anything else (table+prose, image+prose, table+image, ...) → "mixed"

Notes: raster images only (`get_images`); vector-drawn charts are NOT
counted as images (chart understanding lands with the vision phase).
Text is whitespace-normalized; heading/structure recovery is deferred to
chunking (RAG_RULES §2.4 applies there, not to page normalization).
"""

import re
from dataclasses import dataclass, field

import fitz

SUBSTANTIAL_TEXT_CHARS = 50
PDF_MAGIC = b"%PDF-"

TABLE = "table"
VISUAL = "visual"
NARRATIVE = "narrative"
MIXED = "mixed"


class PdfValidationError(Exception):
    """Deterministic failure with a public error code + safe message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PagePayload:
    page_number: int  # 1-based, matching PDF readers and future citations
    text: str
    text_char_count: int
    has_tables: bool
    has_images: bool
    table_count: int
    tables: tuple = ()
    page_type: str = NARRATIVE
    extraction_ok: bool = True
    extraction_error: str | None = None


@dataclass(frozen=True)
class PdfPayload:
    page_count: int
    pages: tuple = field(default_factory=tuple)


def validate_pdf_bytes(data: bytes, *, max_bytes: int, max_pages: int) -> int:
    """Validate size → signature → openability → page cap. Returns page count."""
    if len(data) > max_bytes:
        raise PdfValidationError("file_too_large", "File exceeds the maximum size.")
    if not data.lstrip().startswith(PDF_MAGIC):
        raise PdfValidationError(
            "unsupported_media_type", "Only PDF documents are accepted."
        )
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            count = doc.page_count
    except Exception:
        raise PdfValidationError("corrupt_document", "File is not a readable PDF.")
    if count < 1:
        raise PdfValidationError("corrupt_document", "PDF contains no pages.")
    if count > max_pages:
        raise PdfValidationError(
            "too_many_pages", "PDF exceeds the maximum page count."
        )
    return count


def normalize_text(raw: str) -> str:
    lines = [line.rstrip() for line in raw.splitlines()]
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return collapsed.strip()


def classify_page(*, text_chars: int, table_count: int, has_images: bool) -> str:
    has_tables = table_count > 0
    substantial = text_chars >= SUBSTANTIAL_TEXT_CHARS
    if has_tables and not substantial and not has_images:
        return TABLE
    if has_images and not has_tables and not substantial:
        return VISUAL
    if not has_tables and not has_images:
        return NARRATIVE
    return MIXED


def _detect_tables(page: "fitz.Page") -> list[dict]:
    try:
        found = page.find_tables()
    except Exception:
        return []
    summaries = []
    try:
        tables = list(found)
    except Exception:
        return []
    for table in tables:
        rows = getattr(table, "row_count", None)
        cols = getattr(table, "col_count", None)
        try:
            bbox = [round(float(v), 2) for v in table.bbox]
        except Exception:
            bbox = None
        summaries.append({"bbox": bbox, "rows": rows, "cols": cols})
    return summaries


def extract_pdf(data: bytes) -> PdfPayload:
    """Extract every page. One bad page never kills the document: it is
    recorded with extraction_ok=False while siblings proceed."""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        raise PdfValidationError("corrupt_document", "File is not a readable PDF.")
    payloads = []
    try:
        for index in range(doc.page_count):
            number = index + 1  # 1-based provenance, never renumbered
            try:
                page = doc[index]
                text = normalize_text(page.get_text("text"))
                try:
                    has_images = len(page.get_images(full=True)) > 0
                except Exception:
                    has_images = False
                tables = _detect_tables(page)
                payloads.append(
                    PagePayload(
                        page_number=number,
                        text=text,
                        text_char_count=len(text),
                        has_tables=len(tables) > 0,
                        has_images=has_images,
                        table_count=len(tables),
                        tables=tuple(tables),
                        page_type=classify_page(
                            text_chars=len(text),
                            table_count=len(tables),
                            has_images=has_images,
                        ),
                    )
                )
            except Exception as exc:
                payloads.append(
                    PagePayload(
                        page_number=number,
                        text="",
                        text_char_count=0,
                        has_tables=False,
                        has_images=False,
                        table_count=0,
                        page_type=NARRATIVE,
                        extraction_ok=False,
                        extraction_error=type(exc).__name__,
                    )
                )
    finally:
        doc.close()
    return PdfPayload(page_count=len(payloads), pages=tuple(payloads))
