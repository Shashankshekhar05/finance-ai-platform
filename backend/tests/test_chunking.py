"""Chunking unit tests: pure, deterministic, no database, no model."""

import pytest

from app.services.chunking import (
    MIN_CHUNK_CHARS,
    PageInput,
    chunk_document_pages,
    chunk_page_text,
)

SIZE, OVERLAP = 2000, 256


def _page(
    text: str, number: int = 1, page_type: str = "narrative", tables: bool = False
) -> PageInput:
    return PageInput(
        page_id=f"page-{number}",
        page_number=number,
        text=text,
        page_type=page_type,
        has_tables=tables,
        has_images=False,
        table_count=1 if tables else 0,
        tables=({"bbox": [0, 0, 1, 1], "rows": 2, "cols": 2},) if tables else (),
    )


def test_short_and_visual_pages_skipped() -> None:
    assert chunk_document_pages([_page("tiny")], size=SIZE, overlap=OVERLAP) == []
    assert (
        chunk_document_pages(
            [_page("x" * 10, page_type="visual")], size=SIZE, overlap=OVERLAP
        )
        == []
    )


def test_single_paragraph_page_stays_whole() -> None:
    text = "Revenue grew across every segment this fiscal year. " * 10
    (chunk,) = chunk_document_pages([_page(text)], size=SIZE, overlap=OVERLAP)
    assert chunk.text == text.strip()
    assert chunk.page_number == 1 and chunk.chunk_index == 0
    assert chunk.chunk_type == "text"
    assert chunk.token_count == max(1, len(chunk.text) // 4)


def test_paragraph_boundaries_preserved() -> None:
    paras = [
        "First paragraph about revenue trends. " * 8,
        "Second paragraph about costs. " * 8,
    ]
    chunks = chunk_page_text("\n\n".join(paras), size=400, overlap=0)
    assert len(chunks) == 2
    assert "revenue" in chunks[0] and "costs" in chunks[1]


def test_long_paragraph_splits_on_sentences_not_decimals() -> None:
    para = (
        "The ratio was 5.2 percent in Q1. It rose to 6.8 percent in Q2. "
        "Analysts expect 7.1 percent next quarter. Margins remain healthy. " * 6
    )
    chunks = chunk_page_text(para, size=150, overlap=0)
    assert len(chunks) > 1
    assert all(len(c) <= 160 for c in chunks)
    assert "5.2 percent" in " ".join(chunks)  # decimals never torn apart


def test_hard_split_only_past_budget_on_word_boundary() -> None:
    word = "supercalifragilistic"
    chunks = chunk_page_text(" ".join([word] * 100), size=100, overlap=0)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    assert all(" " not in c or c == c.strip() for c in chunks)


def test_overlap_bridges_chunks_and_stays_bounded() -> None:
    text = (
        " Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India Juliett Kilo Lima "
        * 4
    )
    plain = chunk_page_text(text, size=120, overlap=0)
    bridged = chunk_page_text(text, size=120, overlap=40)
    assert len(bridged) == len(plain) > 1
    assert bridged[1].startswith(plain[0][-40:].lstrip().split(" ", 1)[-1][:10])
    assert all(len(c) <= 120 + 40 for c in bridged)


def test_max_chunk_size_respected() -> None:
    text = ("Sentence one about growth. Sentence two about margins. " * 40).strip()
    for chunk in chunk_page_text(text, size=300, overlap=50):
        assert len(chunk) <= 350


def test_table_page_kept_whole_with_table_type() -> None:
    text = "Revenue 100 Cost 40 Profit 60. " * 6
    (chunk,) = chunk_document_pages(
        [_page(text, page_type="table", tables=True)], size=SIZE, overlap=OVERLAP
    )
    assert chunk.chunk_type == "table"
    assert chunk.metadata["table_count"] == 1
    assert chunk.metadata["tables"][0]["rows"] == 2


def test_mixed_page_with_tables_maps_to_table_chunks() -> None:
    text = "Intro prose about the quarter. " * 10 + "Revenue 100 Cost 40. " * 4
    chunks = chunk_document_pages(
        [_page(text, page_type="mixed", tables=True)], size=SIZE, overlap=OVERLAP
    )
    assert chunks and all(c.chunk_type == "table" for c in chunks)


def test_multi_page_ordering_and_sequential_index() -> None:
    pages = [
        _page("First page revenue content here. " * 6, number=1),
        _page("Second page expense content here. " * 6, number=2),
    ]
    chunks = chunk_document_pages(pages, size=SIZE, overlap=OVERLAP)
    assert [c.page_number for c in chunks] == [1, 2]
    assert [c.chunk_index for c in chunks] == [0, 1]
    assert [c.page_id for c in chunks] == ["page-1", "page-2"]


def test_chunking_is_deterministic() -> None:
    pages = [_page("Deterministic finance text about margins. " * 12, number=1)]
    first = chunk_document_pages(pages, size=500, overlap=64)
    second = chunk_document_pages(pages, size=500, overlap=64)
    assert first == second


def test_minimum_chunk_size_filters_slivers() -> None:
    text = "x" * (MIN_CHUNK_CHARS - 1)
    assert chunk_document_pages([_page(text)], size=SIZE, overlap=OVERLAP) == []


def test_rag_settings_reject_inconsistent_overlap() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg2://u:p@localhost:5432/db",
            jwt_secret_key="test-only-secret-that-is-long-enough-123456",
            rag_chunk_overlap=2000,
            rag_chunk_size=2000,
        )
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg2://u:p@localhost:5432/db",
            jwt_secret_key="test-only-secret-that-is-long-enough-123456",
            rag_top_k=30,
            rag_max_top_k=20,
        )
