"""Finance CRUD + validation: full lifecycle per resource, exact money strings.

Module-scoped tenants keep bcrypt cost paid once per role per module.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import is_database_reachable, tenant_who

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)

REVENUE_BODY = {
    "amount": "1234.50",
    "currency": "USD",
    "record_date": "2025-01-15",
    "segment": "Enterprise",
    "region": "EMEA",
    "fiscal_year": 2025,
    "fiscal_quarter": 1,
}
EXPENSE_BODY = {
    "amount": "99.99",
    "currency": "usd",  # normalized to USD by the API
    "record_date": "2025-02-01",
    "category": "Travel",
    "department": "Sales",
    "vendor": "Acme Air",
}
TRANSACTION_BODY = {
    "occurred_at": "2025-03-01T10:00:00Z",
    "amount": "10.00",
    "currency": "EUR",
    "type": "income",
    "category": "Sales",
    "account": "Operating",
    "reference": "INV-1",
}


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def analyst(clients: TestClient) -> dict:
    return tenant_who(clients, role="analyst")


def _envelope(response, *, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text


def test_revenue_crud_lifecycle(clients: TestClient, analyst: dict) -> None:
    created = clients.post("/revenue", json=REVENUE_BODY, headers=analyst["headers"])
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["amount"] == "1234.50"  # exact Decimal string, never float
    assert body["company_id"] == analyst["company_id"]
    assert body["currency"] == "USD"
    rid = body["id"]

    fetched = clients.get(f"/revenue/{rid}", headers=analyst["headers"])
    assert fetched.status_code == 200
    assert fetched.json()["segment"] == "Enterprise"

    patched = clients.patch(
        f"/revenue/{rid}", json={"segment": "SMB"}, headers=analyst["headers"]
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["segment"] == "SMB"
    assert patched.json()["amount"] == "1234.50"

    deleted = clients.delete(f"/revenue/{rid}", headers=analyst["headers"])
    # Analysts cannot delete: admin only.
    assert deleted.status_code == 403
    assert deleted.json()["error"]["code"] == "insufficient_permissions"


def test_expense_crud_lifecycle(clients: TestClient, analyst: dict) -> None:
    created = clients.post("/expenses", json=EXPENSE_BODY, headers=analyst["headers"])
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["amount"] == "99.99"
    assert body["currency"] == "USD"  # normalized from lowercase input
    assert body["company_id"] == analyst["company_id"]
    eid = body["id"]

    patched = clients.patch(
        f"/expenses/{eid}", json={"vendor": "New Vendor"}, headers=analyst["headers"]
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["vendor"] == "New Vendor"

    fetched = clients.get(f"/expenses/{eid}", headers=analyst["headers"])
    assert fetched.status_code == 200
    assert fetched.json()["category"] == "Travel"


def test_transaction_crud_lifecycle(clients: TestClient, analyst: dict) -> None:
    created = clients.post(
        "/transactions", json=TRANSACTION_BODY, headers=analyst["headers"]
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["amount"] == "10.00"
    assert body["type"] == "income"
    tid = body["id"]

    patched = clients.patch(
        f"/transactions/{tid}",
        json={"description": "March retainer"},
        headers=analyst["headers"],
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["description"] == "March retainer"


def test_unknown_uuid_returns_safe_not_found(
    clients: TestClient, analyst: dict
) -> None:
    missing = str(uuid.uuid4())
    for path in (
        f"/revenue/{missing}",
        f"/expenses/{missing}",
        f"/transactions/{missing}",
    ):
        response = clients.get(path, headers=analyst["headers"])
        _envelope(response, status=404, code="not_found")


@pytest.mark.parametrize(
    ("path", "body", "field"),
    [
        ("/revenue", {**REVENUE_BODY, "amount": "-5.00"}, "amount"),
        ("/revenue", {**REVENUE_BODY, "amount": "10.123"}, "3dp"),
        ("/revenue", {**REVENUE_BODY, "currency": "USDD"}, "currency"),
        ("/revenue", {**REVENUE_BODY, "currency": "US1"}, "currency"),
        (
            "/revenue",
            {**REVENUE_BODY, "fiscal_quarter": 2, "fiscal_year": None},
            "quarter",
        ),
        ("/revenue", {**REVENUE_BODY, "fiscal_quarter": 5}, "quarter-range"),
        (
            "/revenue",
            {**REVENUE_BODY, "company_id": str(uuid.uuid4())},
            "smuggled-scope",
        ),
        ("/expenses", {**EXPENSE_BODY, "category": ""}, "category"),
        ("/expenses", {**EXPENSE_BODY, "amount": "0"}, "zero"),
        ("/transactions", {**TRANSACTION_BODY, "type": "profit"}, "enum"),
        ("/transactions", {**TRANSACTION_BODY, "amount": "0.001"}, "3dp"),
    ],
)
def test_create_validation_rejects_bad_input(
    clients: TestClient, analyst: dict, path: str, body: dict, field: str
) -> None:
    response = clients.post(path, json=body, headers=analyst["headers"])
    _envelope(response, status=422, code="validation_error")


def test_metric_input_validation_unit() -> None:
    """Pure unit: MetricRecordInput rules without touching the database."""
    import datetime

    from pydantic import ValidationError

    from app.schemas.financial_metric import MetricRecordInput

    ok = MetricRecordInput(
        period=datetime.date(2025, 1, 1),
        metric_name="gross_margin",
        value="0.1523",
        computed_by="calculated",
        inputs_ref={"revenue": "100", "cogs": "84.77"},
    )
    assert ok.metric_name == "gross_margin"

    with pytest.raises(ValidationError):
        MetricRecordInput(
            period=datetime.date(2025, 1, 1),
            metric_name="gross_margin",
            value="0.1",
            computed_by="calculated",
            inputs_ref=None,  # calculated metrics must cite inputs
        )
    with pytest.raises(ValidationError):
        MetricRecordInput(
            period=datetime.date(2025, 1, 1),
            metric_name="Bad Name!",
            value="1",
        )
