"""PDF parsing unit tests: no database, no HTTP, deterministic bytes."""

import pytest

from app.services.pdf import (
    PdfValidationError,
    classify_page,
    extract_pdf,
    normalize_text,
    validate_pdf_bytes,
)
from tests.pdf_factories import (
    image_pdf,
    mixed_pdf,
    non_pdf_bytes,
    table_pdf,
    text_pdf,
    truncated_pdf_bytes,
)

LIMITS = {"max_bytes": 1024 * 1024, "max_pages": 200}


def test_validate_accepts_real_pdf() -> None:
    assert validate_pdf_bytes(text_pdf(), **LIMITS) == 2


def test_validate_rejects_oversize() -> None:
    with pytest.raises(PdfValidationError) as exc:
        validate_pdf_bytes(b"x" * 11, max_bytes=10, max_pages=200)
    assert exc.value.code == "file_too_large"


def test_validate_rejects_non_pdf_signature() -> None:
    with pytest.raises(PdfValidationError) as exc:
        validate_pdf_bytes(non_pdf_bytes(), **LIMITS)
    assert exc.value.code == "unsupported_media_type"


def test_validate_rejects_truncated_pdf() -> None:
    with pytest.raises(PdfValidationError) as exc:
        validate_pdf_bytes(truncated_pdf_bytes(), **LIMITS)
    assert exc.value.code in ("unsupported_media_type", "corrupt_document")


def test_validate_rejects_too_many_pages() -> None:
    from tests.pdf_factories import empty_pages_pdf

    with pytest.raises(PdfValidationError) as exc:
        validate_pdf_bytes(empty_pages_pdf(5), max_bytes=1024 * 1024, max_pages=4)
    assert exc.value.code == "too_many_pages"


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("  hello   \n\n\nworld  \n") == "hello\n\nworld"


@pytest.mark.parametrize(
    ("chars", "tables", "images", "expected"),
    [
        (200, 0, False, "narrative"),
        (0, 0, False, "narrative"),  # empty page: no signal either way
        (10, 1, False, "table"),
        (10, 0, True, "visual"),
        (200, 1, False, "mixed"),
        (200, 0, True, "mixed"),
        (10, 1, True, "mixed"),
    ],
)
def test_classify_page_matrix(
    chars: int, tables: int, images: bool, expected: str
) -> None:
    assert (
        classify_page(text_chars=chars, table_count=tables, has_images=images)
        == expected
    )


def test_extract_narrative_pages() -> None:
    payload = extract_pdf(text_pdf())
    assert payload.page_count == 2
    assert [p.page_number for p in payload.pages] == [1, 2]
    for page in payload.pages:
        assert page.page_type == "narrative"
        assert page.extraction_ok is True
        assert "Management discussion" in page.text
        assert page.has_tables is False and page.has_images is False


def test_extract_table_page() -> None:
    (page,) = extract_pdf(table_pdf()).pages
    assert page.page_type == "table"
    assert page.has_tables is True and page.table_count == 1
    assert "Revenue 100" in page.text
    assert page.tables and page.tables[0]["rows"] == 3


def test_extract_image_page() -> None:
    (page,) = extract_pdf(image_pdf()).pages
    assert page.has_images is True
    assert page.page_type == "visual"


def test_extract_mixed_and_narrative_pages() -> None:
    first, second = extract_pdf(mixed_pdf()).pages
    assert first.page_type == "mixed"
    assert first.has_tables is True
    assert second.page_type == "narrative"


def test_extraction_is_deterministic() -> None:
    data = mixed_pdf()
    assert extract_pdf(data) == extract_pdf(data)
