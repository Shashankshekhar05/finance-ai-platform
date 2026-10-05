"""Retrieval integration: real Postgres + pgvector + BGE, tenant-first SQL.

Covers relevance, Top-K, threshold, filters, deterministic order, auth,
idempotent re-indexing, and the critical cross-tenant zero-leak guarantee.
"""

import pytest
from fastapi.testclient import TestClient

from app.db.engine import dispose_engine, get_engine, session_scope
from app.main import create_app
from tests.conftest import is_database_reachable, tenant_who
from tests.retrieval_factories import annual_report_pdf, memo_pdf

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def tenant_a(clients: TestClient) -> dict:
    return tenant_who(clients, role="analyst")


@pytest.fixture(scope="module")
def tenant_b(clients: TestClient) -> dict:
    return tenant_who(clients, role="analyst")


@pytest.fixture(scope="module")
def viewer_a(clients: TestClient) -> dict:
    return tenant_who(clients, role="viewer")


def _upload_and_index(
    clients: TestClient,
    tenant: dict,
    data: bytes,
    title: str,
    fiscal_year: int | None = None,
) -> str:
    form = {"title": title}
    if fiscal_year is not None:
        form["fiscal_year"] = str(fiscal_year)
    uploaded = clients.post(
        "/documents/upload",
        files={"file": ("report.pdf", data, "application/pdf")},
        data=form,
        headers=tenant["headers"],
    )
    assert uploaded.status_code == 201, uploaded.text
    doc_id = uploaded.json()["document"]["id"]
    indexed = clients.post(f"/documents/{doc_id}/index", headers=tenant["headers"])
    assert indexed.status_code == 200, indexed.text
    body = indexed.json()
    assert body["embedding_status"] == "ready"
    assert body["chunk_count"] > 0
    assert body["embedding_model"] == "BAAI/bge-base-en-v1.5"
    return doc_id


@pytest.fixture(scope="module")
def report_a(clients: TestClient, tenant_a: dict) -> str:
    return _upload_and_index(
        clients, tenant_a, annual_report_pdf(), "Annual Report FY2025", fiscal_year=2025
    )


@pytest.fixture(scope="module")
def memo_b(clients: TestClient, tenant_b: dict) -> str:
    return _upload_and_index(clients, tenant_b, memo_pdf(), "Q1 Memo")


def _search(clients: TestClient, headers: dict, **body):
    return clients.post("/documents/search", json=body, headers=headers)


def test_index_is_idempotent(
    clients: TestClient, tenant_a: dict, report_a: str
) -> None:
    again = clients.post(f"/documents/{report_a}/index", headers=tenant_a["headers"])
    assert again.status_code == 200
    first = clients.get(f"/documents/{report_a}", headers=tenant_a["headers"]).json()
    assert again.json()["chunk_count"] == first["chunk_count"]
    # Total chunks for the document did not grow: delete/rebuild, no dupes.
    from app.repositories import chunk_repository

    engine = get_engine()
    try:
        with session_scope(engine) as session:
            import uuid as uuid_lib

            count = chunk_repository.count_for_document(
                session,
                company_id=uuid_lib.UUID(tenant_a["company_id"]),
                document_id=uuid_lib.UUID(report_a),
            )
            assert count == first["chunk_count"] > 0
    finally:
        dispose_engine()


def test_index_rejects_unknown_and_unready(
    clients: TestClient, tenant_a: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        clients.post(
            "/documents/00000000-0000-0000-0000-000000000000/index",
            headers=tenant_a["headers"],
        ).status_code
        == 404
    )

    import app.services.ingest_service as ingest
    from app.services.pdf import PdfValidationError

    def _boom(data: bytes):  # type: ignore[no-untyped-def]
        raise PdfValidationError("corrupt_document", "Simulated crash.")

    monkeypatch.setattr(ingest, "extract_pdf", _boom)
    data = annual_report_pdf()
    uploaded = clients.post(
        "/documents/upload",
        files={"file": ("bad.pdf", data, "application/pdf")},
        data={"title": "Bad"},
        headers=tenant_a["headers"],
    )
    assert uploaded.status_code == 422
    from hashlib import sha256

    digest = sha256(data).hexdigest()
    failed = next(
        item
        for item in clients.get(
            "/documents", params={"status": "failed"}, headers=tenant_a["headers"]
        ).json()["items"]
        if item["sha256_hash"] == digest
    )
    assert (
        clients.post(
            f"/documents/{failed['id']}/index", headers=tenant_a["headers"]
        ).status_code
        == 409
    )


def test_search_finds_revenue_page(
    clients: TestClient, tenant_a: dict, report_a: str
) -> None:
    response = _search(
        clients, tenant_a["headers"], query="What was revenue in FY2025?", top_k=3
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) >= 1
    assert results[0]["page_number"] == 1
    assert "embedding" not in response.text
    first = results[0]
    assert first["document_id"] == report_a
    assert first["document_title"] == "Annual Report FY2025"
    assert set(first) == {
        "chunk_id",
        "document_id",
        "document_title",
        "page_number",
        "chunk_index",
        "chunk_type",
        "text",
        "score",
    }
    assert 0.0 < first["score"] <= 1.0


def test_top_k_bounds_results(
    clients: TestClient, tenant_a: dict, report_a: str
) -> None:
    one = _search(clients, tenant_a["headers"], query="expenses", top_k=1).json()
    three = _search(clients, tenant_a["headers"], query="expenses", top_k=3).json()
    assert len(one["results"]) == 1
    assert 1 <= len(three["results"]) <= 3
    assert (
        _search(clients, tenant_a["headers"], query="expenses", top_k=1000).status_code
        == 422
    )


def test_threshold_filters_weak_hits(
    clients: TestClient, tenant_a: dict, report_a: str
) -> None:
    from app.core.config import get_settings
    from app.db.engine import get_engine, session_scope
    from app.services import search_service
    import uuid as uuid_lib

    engine = get_engine()
    try:
        with session_scope(engine) as session:
            settings = get_settings().model_copy(
                update={"rag_similarity_threshold": 0.9999}
            )
            response = search_service.search_evidence(
                session,
                company_id=uuid_lib.UUID(tenant_a["company_id"]),
                query="revenue fiscal 2025",
                top_k=5,
                document_id=None,
                fiscal_year=None,
                page_number=None,
                settings=settings,
            )
            assert response.results == []
    finally:
        dispose_engine()


def test_document_and_page_filters(
    clients: TestClient, tenant_a: dict, report_a: str
) -> None:
    headers = tenant_a["headers"]
    other = _upload_and_index(
        clients, tenant_a, memo_pdf(), "Second Memo", fiscal_year=2024
    )
    by_doc = _search(
        clients, headers, query="office", top_k=5, document_id=other
    ).json()
    assert by_doc["results"]
    assert {hit["document_id"] for hit in by_doc["results"]} == {other}
    by_year = _search(
        clients, headers, query="revenue", top_k=5, fiscal_year=2025
    ).json()
    assert by_year["results"]
    assert {hit["document_id"] for hit in by_year["results"]} == {report_a}
    by_page = _search(clients, headers, query="revenue", top_k=5, page_number=2).json()
    assert by_page["results"]
    assert {hit["page_number"] for hit in by_page["results"]} == {2}


def test_ordering_is_deterministic(
    clients: TestClient, tenant_a: dict, report_a: str
) -> None:
    headers = tenant_a["headers"]
    first = _search(clients, headers, query="fiscal year results", top_k=5).json()
    second = _search(clients, headers, query="fiscal year results", top_k=5).json()
    assert [hit["chunk_id"] for hit in first["results"]] == [
        hit["chunk_id"] for hit in second["results"]
    ]


def test_search_auth(clients: TestClient, viewer_a: dict, report_a: str) -> None:
    assert clients.post("/documents/search", json={"query": "x"}).status_code == 401
    # Viewers may search (their own tenant scope); empty scope → empty results.
    own = _search(clients, viewer_a["headers"], query="anything", top_k=2)
    assert own.status_code == 200
    assert own.json()["results"] == []


def test_cross_tenant_zero_leak(
    clients: TestClient, tenant_a: dict, tenant_b: dict, report_a: str, memo_b: str
) -> None:
    """Company B asks Company A's questions: zero Company A chunks, ever."""
    for query in (
        "What was revenue in FY2025?",
        "What were operating expenses?",
        "What was EBITDA?",
    ):
        response = _search(clients, tenant_b["headers"], query=query, top_k=5)
        assert response.status_code == 200, response.text
        for hit in response.json()["results"]:
            assert hit["document_id"] != report_a
    # And A never sees B's memo.
    response = _search(
        clients, tenant_a["headers"], query="cafeteria lunch hours parking", top_k=5
    )
    assert response.status_code == 200
    for hit in response.json()["results"]:
        assert hit["document_id"] != memo_b
