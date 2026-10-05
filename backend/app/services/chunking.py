"""Deterministic semantic chunking: page payloads → ordered chunk payloads.

Pure functions (no DB, no model, no I/O): same page text + same config →
same chunks, same order. Hierarchy actually implemented:

1. page boundaries (never crossed — RAG_RULES §3.1),
2. paragraph boundaries (blank-line separated blocks stay whole),
3. sentence boundaries (split long paragraphs; regex avoids decimals like
   "5.2" via a capital-letter lookahead — heuristic, documented),
4. hard size split (only past chunk_size, on a word boundary).

Guards: pages with < MIN_CHUNK_CHARS are skipped (nothing worth embedding)
— visual-only/empty pages therefore produce zero chunks, deterministically.
Table pages keep whole-page text in ONE chunk while it fits (never split a
logical table blindly); oversized table text falls back to the same
paragraph packing. Overlap trails the previous chunk up to overlap chars,
cut at a word boundary, and is validated < size in Settings.

Sizes are CHARACTERS (~4 chars/token for BGE); token_count is recorded as
chars//4 and documented as an estimate, not a tokenizer count.
"""

import re
from dataclasses import dataclass, field

MIN_CHUNK_CHARS = 50

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\u201c])")


@dataclass(frozen=True)
class ChunkPayload:
    page_id: str
    page_number: int
    chunk_index: int  # per-document sequence, assigned by the caller
    text: str
    chunk_type: str  # "text" | "table"
    char_count: int
    token_count: int
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PageInput:
    page_id: str
    page_number: int
    text: str
    page_type: str  # narrative | table | visual | mixed
    has_tables: bool
    has_images: bool
    table_count: int
    tables: tuple = ()


def _split_sentences(paragraph: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(paragraph.strip())
    return [part.strip() for part in parts if part.strip()]


def _pack_units(units: list[str], *, size: int) -> list[str]:
    """Greedily pack units (paragraphs/sentences) into ≤size char chunks."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for unit in units:
        piece = unit
        while len(piece) > size:
            # Hard split only when a single unit exceeds the budget.
            if current:
                chunks.append(" ".join(current))
                current, current_len = [], 0
            cut = piece.rfind(" ", 0, size)
            cut = cut if cut > 0 else size
            chunks.append(piece[:cut])
            piece = piece[cut:].lstrip()
        add = len(piece) + (1 if current else 0)
        if current and current_len + add > size:
            chunks.append(" ".join(current))
            current, current_len = [], 0
        current.append(piece)
        current_len += len(piece) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append(" ".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


def _with_overlap(chunks: list[str], *, overlap: int) -> list[str]:
    """Prefix each chunk (after the first) with the previous chunk's tail,
    cut back to a word boundary. Overlap < size is enforced by Settings."""
    if overlap <= 0 or len(chunks) < 2:
        return chunks
    out = [chunks[0]]
    for previous, current in zip(chunks, chunks[1:]):
        tail = previous[-overlap:].lstrip()
        space = tail.find(" ")
        bridge = tail[space + 1 :] if space >= 0 else tail
        out.append(f"{bridge} {current}" if bridge else current)
    return out


def chunk_page_text(text: str, *, size: int, overlap: int) -> list[str]:
    """Split one page's text into ordered chunk strings (no page metadata)."""
    paragraphs = [p.strip() for p in text.split("\n\n")]
    paragraphs = [p for p in paragraphs if p]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= size:
            units.append(paragraph)
        else:
            units.extend(_split_sentences(paragraph))
    packed = _pack_units(units, size=size)
    return _with_overlap(packed, overlap=overlap)


def chunk_document_pages(
    pages: list[PageInput], *, size: int, overlap: int
) -> list[ChunkPayload]:
    """Chunk a document's pages in page order. Index assigned sequentially."""
    payloads: list[ChunkPayload] = []
    index = 0
    for page in pages:
        text = page.text.strip()
        if len(text) < MIN_CHUNK_CHARS:
            continue  # empty / visual-only / noise: skip deterministically
        chunk_type = "table" if page.has_tables else "text"
        for piece in chunk_page_text(text, size=size, overlap=overlap):
            if len(piece.strip()) < MIN_CHUNK_CHARS:
                continue
            payloads.append(
                ChunkPayload(
                    page_id=page.page_id,
                    page_number=page.page_number,
                    chunk_index=index,
                    text=piece,
                    chunk_type=chunk_type,
                    char_count=len(piece),
                    token_count=max(1, len(piece) // 4),
                    metadata={
                        "page_type": page.page_type,
                        "has_images": page.has_images,
                        "table_count": page.table_count,
                        "tables": list(page.tables),
                    },
                )
            )
            index += 1
    return payloads
