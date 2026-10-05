"""Evidence packet: the ONLY thing the LLM ever sees, besides the question.

Pure data + pure builders (no DB, no HTTP, no secrets). Backend assigns
every evidence ID ([CALC-n]/[DOC-n]); the LLM may reference them but never
invent them. Tenant scoping happens upstream — builders take already-scoped
results and never touch sessions, tokens, or repositories.

Ordering is deterministic: calculation items first (authoritative, in
result order), then document items (search rank order). Budgets truncate
document text only (calculations are small and authoritative); truncation
is marked so nothing is silently thinned.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

SourceType = Literal["calculation", "document", "data"]


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str  # [CALC-1], [DOC-1], ...
    source_type: SourceType
    # Calculation payload (exact strings from the engine, never recomputed).
    dataset: str | None = None
    operation: str | None = None
    value_text: str | None = None
    unit: str | None = None
    currency: str | None = None
    record_count: int | None = None
    # Document payload (untrusted text, provenance for citations).
    document_id: str | None = None
    document_title: str | None = None
    page_number: int | None = None
    chunk_id: str | None = None
    text: str | None = None
    score: float | None = None
    truncated: bool = False
    # Structured-row payload (tenant-scoped list rows for the SQL route).
    label: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class EvidencePacket:
    items: tuple[EvidenceItem, ...] = ()
    valid_ids: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def build(
        cls,
        *,
        calculations: list[Any] | None = None,
        documents: list[Any] | None = None,
        data: list[Any] | None = None,
        max_items: int = 10,
        max_chars: int = 2000,
    ) -> "EvidencePacket":
        """Assemble IDs + truncate. Accepts CalculationResponse-likes,
        SearchHit-likes, and (label, details-dict) data rows. Order is
        calcs → docs → data, each in input order (deterministic)."""
        items: list[EvidenceItem] = []
        for index, calc in enumerate(calculations or [], start=1):
            items.append(_from_calculation(calc, index))
        for index, hit in enumerate(documents or [], start=1):
            items.append(_from_document(hit, index, max_chars=max_chars))
        for index, row in enumerate(data or [], start=1):
            items.append(_from_data(row, index))
        items = items[:max_items]
        return cls(
            items=tuple(items), valid_ids=frozenset(i.evidence_id for i in items)
        )


def _calc_value(calc: Any) -> str | None:
    kind = getattr(calc, "kind", None)
    if kind == "single":
        return getattr(calc, "value", None)
    if kind == "grouped":
        parts = [
            f"{g.dimensions}={g.value}" for g in (getattr(calc, "groups", None) or [])
        ]
        return "; ".join(parts) or None
    if kind == "comparison":
        current = getattr(calc, "current_value", None)
        comparison = getattr(calc, "comparison_value", None)
        percent = getattr(calc, "percent_value", None)
        absolute = getattr(calc, "absolute_variance", None)
        bits = [f"current={current}", f"comparison={comparison}"]
        if absolute is not None:
            bits.append(f"absolute_variance={absolute}")
        if percent is not None:
            bits.append(f"percent={percent}")
        return "; ".join(bits)
    if kind == "margin":
        return (
            f"revenue={getattr(calc, 'revenue_value', None)}; "
            f"expense={getattr(calc, 'expense_value', None)}; "
            f"absolute={getattr(calc, 'absolute_value', None)}; "
            f"margin_percent={getattr(calc, 'margin_percent', None)}"
        )
    return None


def _from_calculation(calc: Any, index: int) -> EvidenceItem:
    provenance = getattr(calc, "provenance", None)
    return EvidenceItem(
        evidence_id=f"[CALC-{index}]",
        source_type="calculation",
        dataset=getattr(calc, "dataset", None),
        operation=getattr(calc, "operation", None),
        value_text=_calc_value(calc),
        unit=getattr(calc, "unit", None),
        currency=getattr(calc, "currency", None),
        record_count=getattr(provenance, "record_count", None),
    )


def _from_document(hit: Any, index: int, *, max_chars: int) -> EvidenceItem:
    text = getattr(hit, "text", "") or ""
    truncated = len(text) > max_chars
    return EvidenceItem(
        evidence_id=f"[DOC-{index}]",
        source_type="document",
        document_id=str(getattr(hit, "document_id", "")),
        document_title=getattr(hit, "document_title", None),
        page_number=getattr(hit, "page_number", None),
        chunk_id=str(getattr(hit, "chunk_id", "")),
        text=text[:max_chars] if truncated else text,
        score=getattr(hit, "score", None),
        truncated=truncated,
    )


def _from_data(row: Any, index: int) -> EvidenceItem:
    """Structured list row → labeled key/value lines (tenant-scoped upstream).

    Accepts (label, details) or (label, details, dataset); the dataset feeds
    citation provenance, never the prompt body.
    """
    if isinstance(row, tuple) and len(row) == 3:
        label, details, dataset = row
    else:
        label, details = row if isinstance(row, tuple) else (str(row), {})
        dataset = None
    return EvidenceItem(
        evidence_id=f"[DATA-{index}]",
        source_type="data",
        dataset=dataset,
        label=str(label),
        details={str(key): value for key, value in dict(details or {}).items()},
    )
