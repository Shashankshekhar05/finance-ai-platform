"""Document API: upload validation, provenance, dedupe, failure, tenancy."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.pdf import PdfValidationError
from tests.conftest import is_database_reachable, tenant_who
from tests.pdf_factories import (
    mixed_pdf,
    non_pdf_bytes,
    table_pdf,
    text_pdf,
    truncated_pdf_bytes,
)

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def analyst(clients: TestClient) -> dict:
    return tenant_who(clients, role="analyst")


@pytest.fixture(scope="module")
def viewer(clients: TestClient) -> dict:
    return tenant_who(clients, role="viewer")


@pytest.fixture(scope="module")
def tenant_b(clients: TestClient) -> dict:
    return tenant_who(clients, role="analyst")


def _upload(
    clients: TestClient,
    headers: dict,
    data: bytes,
    filename: str = "report.pdf",
    content_type: str = "application/pdf",
    title: str = "Q1 Report",
    fiscal_year: int | None = 2025,
):
    form = {"title": title}
    if fiscal_year is not None:
        form["fiscal_year"] = str(fiscal_year)
    return clients.post(
        "/documents/upload",
        files={"file": (filename, data, content_type)},
        data=form,
        headers=headers,
    )


def _envelope(response, *, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text


def test_upload_happy_path_with_provenance(clients: TestClient, analyst: dict) -> None:
    response = _upload(clients, analyst["headers"], mixed_pdf())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["duplicate"] is False
    doc = body["document"]
    assert doc["status"] == "indexed"
    assert doc["page_count"] == 2
    assert doc["company_id"] == analyst["company_id"]
    assert doc["title"] == "Q1 Report" and doc["fiscal_year"] == 2025
    assert doc["sha256_hash"] and doc["file_size"] > 0
    assert "storage_key" not in response.text  # tenant internals stay inside

    pages = clients.get(f"/documents/{doc['id']}/pages", headers=analyst["headers"])
    assert pages.status_code == 200
    items = pages.json()
    assert [p["page_number"] for p in items] == [1, 2]  # 1-based, never renumbered
    assert [p["page_type"] for p in items] == ["mixed", "narrative"]
    for page in items:
        assert page["document_id"] == doc["id"]
        assert page["company_id"] == analyst["company_id"]
        assert page["extraction_status"] == "ok"
    assert "Management discussion" in items[1]["extracted_text"]

    detail = clients.get(f"/documents/{doc['id']}", headers=analyst["headers"])
    assert detail.status_code == 200
    assert detail.json()["original_filename"] == "report.pdf"


def test_upload_table_page_flags(clients: TestClient, analyst: dict) -> None:
    response = _upload(clients, analyst["headers"], table_pdf(), title="Tables")
    assert response.status_code == 201, response.text
    doc_id = response.json()["document"]["id"]
    (page,) = clients.get(
        f"/documents/{doc_id}/pages", headers=analyst["headers"]
    ).json()
    assert page["page_type"] == "table"
    assert page["has_tables"] is True and page["table_count"] == 1


def test_upload_rejects_unauthenticated_and_viewer(
    clients: TestClient, viewer: dict
) -> None:
    response = clients.post(
        "/documents/upload",
        files={"file": ("r.pdf", text_pdf(), "application/pdf")},
        data={"title": "X"},
    )
    assert response.status_code == 401
    forbidden = _upload(clients, viewer["headers"], text_pdf())
    _envelope(forbidden, status=403, code="insufficient_permissions")


def test_upload_rejects_non_pdf(clients: TestClient, analyst: dict) -> None:
    headers = analyst["headers"]
    # Wrong MIME + extension.
    _envelope(
        _upload(
            clients,
            headers,
            non_pdf_bytes(),
            filename="notes.txt",
            content_type="text/plain",
        ),
        status=422,
        code="unsupported_media_type",
    )
    # Lies about being a PDF: extension/MIME say PDF, magic bytes do not.
    _envelope(
        _upload(
            clients,
            headers,
            non_pdf_bytes(),
            filename="fake.pdf",
            content_type="application/pdf",
        ),
        status=422,
        code="unsupported_media_type",
    )
    # PDF header but truncated body.
    _envelope(
        _upload(clients, headers, truncated_pdf_bytes()),
        status=422,
        code="corrupt_document",
    )
    # Bad form fields.
    _envelope(
        _upload(clients, headers, text_pdf(), title=""),
        status=422,
        code="validation_error",
    )


def test_upload_rejects_oversize_and_too_many_pages(
    clients: TestClient, analyst: dict
) -> None:
    from tests.pdf_factories import empty_pages_pdf

    headers = analyst["headers"]
    _envelope(
        _upload(clients, headers, b"x" * (25 * 1024 * 1024 + 1)),
        status=413,
        code="file_too_large",
    )
    _envelope(
        _upload(clients, headers, empty_pages_pdf(201)),
        status=422,
        code="too_many_pages",
    )


def test_upload_dedupes_within_company_not_across(
    clients: TestClient, analyst: dict, tenant_b: dict
) -> None:
    data = text_pdf()
    first = _upload(clients, analyst["headers"], data, title="Original")
    assert first.status_code == 201
    first_id = first.json()["document"]["id"]
    second = _upload(clients, analyst["headers"], data, title="Again")
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True
    assert second.json()["document"]["id"] == first_id
    # Same bytes, other tenant: independent row, fresh ingest.
    third = _upload(clients, tenant_b["headers"], data, title="B copy")
    assert third.status_code == 201, third.text
    assert third.json()["duplicate"] is False
    assert third.json()["document"]["id"] != first_id


def test_failed_document_persists_and_reprocesses(
    clients: TestClient, analyst: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.ingest_service as ingest

    def _boom(data: bytes):  # type: ignore[no-untyped-def]
        raise PdfValidationError("corrupt_document", "Simulated extraction crash.")

    monkeypatch.setattr(ingest, "extract_pdf", _boom)
    data = text_pdf()
    failed = _upload(clients, analyst["headers"], data, title="Doomed")
    _envelope(failed, status=422, code="corrupt_document")

    listed = clients.get(
        "/documents", params={"status": "failed"}, headers=analyst["headers"]
    ).json()
    # The failed row exists with a typed code (found by sha among failed rows).
    from hashlib import sha256

    target = sha256(data).hexdigest()
    failed_ids = [
        item["id"] for item in listed["items"] if item["sha256_hash"] == target
    ]
    assert len(failed_ids) == 1
    detail = clients.get(
        f"/documents/{failed_ids[0]}", headers=analyst["headers"]
    ).json()
    assert detail["status"] == "failed"
    assert detail["ingestion_error_code"] == "corrupt_document"

    # Re-upload while failed retries in place (no second row).
    retry_upload = _upload(clients, analyst["headers"], data, title="Doomed")
    assert retry_upload.status_code == 422  # still patched → still failing

    monkeypatch.undo()
    healed = clients.post(
        f"/documents/{failed_ids[0]}/reprocess", headers=analyst["headers"]
    )
    assert healed.status_code == 200, healed.text
    assert healed.json()["status"] == "indexed"
    assert healed.json()["page_count"] == 2

    # Reprocessing a healthy document is a conflict, not a silent no-op.
    _envelope(
        clients.post(
            f"/documents/{failed_ids[0]}/reprocess", headers=analyst["headers"]
        ),
        status=409,
        code="invalid_state",
    )
    _envelope(
        clients.post(
            "/documents/00000000-0000-0000-0000-000000000000/reprocess",
            headers=analyst["headers"],
        ),
        status=404,
        code="not_found",
    )


def test_cross_tenant_documents_isolated(
    clients: TestClient, analyst: dict, tenant_b: dict
) -> None:
    owned = _upload(clients, analyst["headers"], text_pdf(), title="Private")
    doc_id = owned.json()["document"]["id"]
    _envelope(
        clients.get(f"/documents/{doc_id}", headers=tenant_b["headers"]),
        status=404,
        code="not_found",
    )
    _envelope(
        clients.get(f"/documents/{doc_id}/pages", headers=tenant_b["headers"]),
        status=404,
        code="not_found",
    )
    _envelope(
        clients.post(f"/documents/{doc_id}/reprocess", headers=tenant_b["headers"]),
        status=404,
        code="not_found",
    )
    listed = clients.get("/documents", headers=tenant_b["headers"]).json()
    assert all(item["company_id"] == tenant_b["company_id"] for item in listed["items"])
    assert doc_id not in {item["id"] for item in listed["items"]}


def test_list_pagination_and_status_filter(clients: TestClient, analyst: dict) -> None:
    headers = analyst["headers"]
    for i in range(3):
        _upload(clients, headers, text_pdf(), title=f"Paged {i}")
    first = clients.get(
        "/documents", params={"limit": 2, "offset": 0}, headers=headers
    ).json()
    assert first["limit"] == 2 and first["total"] >= 3 and len(first["items"]) == 2
    second = clients.get(
        "/documents", params={"limit": 2, "offset": 2}, headers=headers
    ).json()
    assert {i["id"] for i in first["items"]}.isdisjoint(
        {i["id"] for i in second["items"]}
    )
    indexed = clients.get(
        "/documents", params={"status": "indexed"}, headers=headers
    ).json()
    assert all(item["status"] == "indexed" for item in indexed["items"])
    assert (
        clients.get("/documents", params={"limit": 201}, headers=headers).status_code
        == 422
    )
    assert (
        clients.get(
            "/documents", params={"status": "bogus"}, headers=headers
        ).status_code
        == 422
    )


def test_storage_key_is_safe_despite_evil_filename(
    clients: TestClient, analyst: dict
) -> None:
    import pathlib

    data = text_pdf()
    response = _upload(
        clients, analyst["headers"], data, filename="../../evil.pdf", title="Evil"
    )
    assert response.status_code == 201, response.text
    doc = response.json()["document"]
    assert doc["original_filename"].endswith("evil.pdf")
    assert ".." not in doc.get("storage_key", "")
    assert "storage_key" not in doc
    # The bytes landed under the generated key inside the storage root.
    expected = (
        pathlib.Path("./storage/documents") / analyst["company_id"] / f"{doc['id']}.pdf"
    )
    assert expected.is_file()
    assert expected.read_bytes() == data


def test_viewer_reads_own_company_but_never_writes(
    clients: TestClient, viewer: dict
) -> None:
    # Viewer reads are allowed (own, empty company) and scoped...
    listed = clients.get("/documents", headers=viewer["headers"])
    assert listed.status_code == 200, listed.text
    assert all(
        item["company_id"] == viewer["company_id"] for item in listed.json()["items"]
    )
    # ...while writes stay forbidden and anonymous reads stay out.
    _envelope(
        _upload(clients, viewer["headers"], text_pdf()),
        status=403,
        code="insufficient_permissions",
    )
    assert clients.get("/documents").status_code == 401
