"""Grounded answer orchestration: trusted evidence → Groq → validated answer.

Read-only end to end (no commits, no writes). Order of operations:
  1. Resolve evidence specs through tenant-scoped backend services.
  2. Empty packet → insufficient_evidence WITHOUT any provider call.
  3. Missing API key → 503 (the app works fine without a key otherwise).
  4. Build prompt → single provider call (no retries, no tools).
  5. Parse + validate citations: unknown IDs are STRIPPED and the answer is
     flagged citation_invalid (deterministic; at most zero retries).
Claim-level completeness (every factual sentence cited) is NOT enforced —
that needs NLP, not rules; validity of every cited ID IS enforced.
"""

import logging
import re
import time
import uuid

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import raise_api_error
from app.schemas.ai import AnswerResponse, Citation
from app.schemas.calculation import CalculationRequest
from app.schemas.retrieval import SearchRequest
from app.services import calculation_service, search_service
from app.services.evidence import EvidencePacket
from app.services.groq_client import (
    GroqAuthError,
    GroqBadRequestError,
    GroqClient,
    GroqMalformedError,
    GroqModelError,
    GroqNetworkError,
    GroqRateLimitError,
    GroqServerError,
    GroqTimeoutError,
    HttpGroqClient,
)
from app.services.prompt import build_messages

logger = logging.getLogger(__name__)

_OPENERS = "\[\[\u3010\u300c\u300e\u27e8\u300a\ufe5d\uff3b"
_CLOSERS = "\\]\u3011\u300d\u300f\u27e9\u300b\ufe5e\uff3d"
_HYPHENS = "\-\u2010\u2011\u2012\u2013\u2014\uff0d"
_DIGITS = "0-9\uff10-\uff19"
_CITATION_RE = re.compile(
    f"[{_OPENERS}]((?:DOC|CALC|DATA))[{_HYPHENS}]([{_DIGITS}]+)[{_CLOSERS}]"
)
_FW_DIGITS = {chr(0xFF10 + i): str(i) for i in range(10)}


def _canonicalize(kind: str, number: str) -> str:
    """Map a detected citation spelling to canonical `[KIND-n]` form."""
    digits = "".join(_FW_DIGITS.get(ch, ch) for ch in number).lstrip("0") or "0"
    return f"[{kind}-{digits}]"


def validate_citations(
    text: str, valid_ids: frozenset[str]
) -> tuple[str, list[str], bool]:
    """Return (cleaned text, valid canonical IDs in order, had_unknown).

    Detection tolerates common Unicode bracket/hyphen/digit variants
    (e.g. 【CALC-1】, DOC‑1 with U+2011); validation always runs against
    canonical IDs. Valid citations stay in the text EXACTLY as the model
    wrote them; only unknown citations' original spans are stripped.
    """
    seen_canonical: list[str] = []
    unknown_spans: list[str] = []
    for match in _CITATION_RE.finditer(text):
        canonical = _canonicalize(match.group(1), match.group(2))
        if canonical in valid_ids:
            if canonical not in seen_canonical:
                seen_canonical.append(canonical)
        elif match.group(0) not in unknown_spans:
            unknown_spans.append(match.group(0))
    cleaned = text
    for span in unknown_spans:
        cleaned = cleaned.replace(span, "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    if unknown_spans and not cleaned:
        cleaned = "The generated answer failed citation validation."
    return cleaned, seen_canonical, bool(unknown_spans)


_INSUFFICIENT_ANSWER = (
    "I don't have enough verified evidence to answer that. "
    "Try narrowing the question or adding the relevant records first."
)


def _fail(status_code: int, code: str):  # type: ignore[no-untyped-def]
    raise raise_api_error(status_code, code)


def answer_question(
    session: Session,
    *,
    company_id: uuid.UUID,
    question: str,
    calculation: CalculationRequest | None = None,
    retrieval: SearchRequest | None = None,
    settings: Settings,
    llm_client: GroqClient | None = None,
    packet: EvidencePacket | None = None,
    history: list[tuple[str, str]] | None = None,
) -> AnswerResponse:
    """Answer from evidence, with optional bounded conversation context.

    `history` is supporting context only: it renders inside a delimited
    conversation block and NEVER feeds evidence, citations, or numbers.
    Omitted history preserves the exact legacy prompt (byte-identical).
    Packet injection seam (Phase 8): callers that already assembled a
    tenant-scoped packet may pass it directly; when omitted, the packet is
    built from the calculation/retrieval specs exactly as before.
    """
    started = time.perf_counter()
    if packet is None:
        calc_results = []
        if calculation is not None:
            calc_results.append(
                calculation_service.calculate(
                    session, company_id=company_id, request=calculation
                )
            )
        doc_hits = []
        if retrieval is not None:
            doc_hits = search_service.search_evidence(
                session,
                company_id=company_id,
                query=retrieval.query,
                top_k=retrieval.top_k,
                document_id=retrieval.document_id,
                fiscal_year=retrieval.fiscal_year,
                page_number=retrieval.page_number,
                settings=settings,
            ).results

        packet = EvidencePacket.build(
            calculations=calc_results,
            documents=doc_hits,
            max_items=settings.ai_max_evidence_items,
            max_chars=settings.ai_max_evidence_chars,
        )
    if not packet.items:
        logger.info(
            "answer company_id=%s status=insufficient_evidence evidence=0 (no provider call)",
            company_id,
        )
        return AnswerResponse(
            status="insufficient_evidence", answer=_INSUFFICIENT_ANSWER, citations=[]
        )

    if llm_client is not None:
        client = llm_client
    else:
        # Production path (the route guard usually guarantees a key first).
        if settings.groq_api_key is None:
            _fail(status.HTTP_503_SERVICE_UNAVAILABLE, "llm_unavailable")
        client = HttpGroqClient(
            api_key=settings.groq_api_key or "", base_url=settings.groq_base_url
        )
    messages = build_messages(question=question, packet=packet, history=history)
    try:
        response = client.complete(
            messages=messages,
            model=settings.groq_model,
            temperature=settings.groq_temperature,
            max_tokens=settings.groq_max_output_tokens,
            timeout_s=settings.groq_timeout_seconds,
        )
    except (GroqTimeoutError, GroqNetworkError, GroqServerError, GroqRateLimitError):
        _fail(status.HTTP_503_SERVICE_UNAVAILABLE, "llm_unavailable")
    except (GroqAuthError, GroqModelError, GroqBadRequestError, GroqMalformedError):
        _fail(status.HTTP_502_BAD_GATEWAY, "llm_error")

    cleaned, valid_ids, had_unknown = validate_citations(
        response.text, packet.valid_ids
    )
    by_id = {item.evidence_id: item for item in packet.items}
    citations = [
        Citation(
            evidence_id=token,
            source_type=by_id[token].source_type,
            document_title=by_id[token].document_title,
            page_number=by_id[token].page_number,
            chunk_id=by_id[token].chunk_id,
            dataset=by_id[token].dataset,
            operation=by_id[token].operation,
        )
        for token in valid_ids
    ]
    answer_status = "citation_invalid" if had_unknown else "grounded"
    logger.info(
        "answer company_id=%s status=%s evidence=%s model=%s latency_ms=%s question=%.120s",
        company_id,
        answer_status,
        len(packet.items),
        settings.groq_model,
        response.latency_ms,
        question,
    )
    logger.debug(
        "answer timings company_id=%s total_ms=%s",
        company_id,
        int((time.perf_counter() - started) * 1000),
    )
    return AnswerResponse(status=answer_status, answer=cleaned, citations=citations)
