"""Finance tenancy: Company A can never touch Company B's money.

Unknown and foreign UUIDs both answer 404 (no existence leakage); lists
are scoped; metrics inherit the same scoping through the shared path.
"""

import datetime
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.engine import dispose_engine, get_engine, session_scope
from app.main import create_app
from app.schemas.financial_metric import MetricRecordInput
from app.services import metric_service
from tests.conftest import is_database_reachable, tenant_who
from tests.test_finance_crud import EXPENSE_BODY, REVENUE_BODY, TRANSACTION_BODY

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
def admin_a(clients: TestClient) -> dict:
    return tenant_who(clients, role="admin")


def _seed(clients: TestClient, tenant: dict) -> dict[str, str]:
    ids = {}
    for path, body in (
        ("/revenue", REVENUE_BODY),
        ("/expenses", EXPENSE_BODY),
        ("/transactions", TRANSACTION_BODY),
    ):
        response = clients.post(path, json=body, headers=tenant["headers"])
        assert response.status_code == 201, response.text
        ids[path] = response.json()["id"]

    engine = get_engine()
    try:
        with session_scope(engine) as session:
            metric = metric_service.record_metric(
                session,
                company_id=uuid.UUID(tenant["company_id"]),
                data=MetricRecordInput(
                    period=datetime.date(2025, 1, 1),
                    metric_name="gross_margin",
                    value="0.25",
                    computed_by="reported",
                ),
            )
            ids["/financial-metrics"] = str(metric.id)
    finally:
        dispose_engine()
    return ids


def test_cross_tenant_read_returns_not_found(
    clients: TestClient, tenant_a: dict, tenant_b: dict
) -> None:
    ids = _seed(clients, tenant_b)
    for path, rid in ids.items():
        response = clients.get(f"{path}/{rid}", headers=tenant_a["headers"])
        assert response.status_code == 404, (path, response.text)
        assert response.json()["error"]["code"] == "not_found"


def test_cross_tenant_write_and_delete_blocked(
    clients: TestClient, tenant_a: dict, tenant_b: dict, admin_a: dict
) -> None:
    ids = _seed(clients, tenant_b)
    rid = ids["/revenue"]
    assert (
        clients.patch(
            f"/revenue/{rid}", json={"segment": "X"}, headers=tenant_a["headers"]
        ).status_code
        == 404
    )
    eid = ids["/expenses"]
    assert (
        clients.patch(
            f"/expenses/{eid}", json={"vendor": "X"}, headers=tenant_a["headers"]
        ).status_code
        == 404
    )
    # Even an admin of A cannot delete B's row: the tenant filter runs first.
    tid = ids["/transactions"]
    response = clients.delete(f"/transactions/{tid}", headers=admin_a["headers"])
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
    assert (
        clients.get(f"/revenue/{rid}", headers=tenant_a["headers"]).status_code == 404
    )


def test_list_endpoints_are_tenant_scoped(
    clients: TestClient, tenant_a: dict, tenant_b: dict
) -> None:
    _seed(clients, tenant_a)
    own = clients.get("/revenue", headers=tenant_a["headers"]).json()
    assert own["total"] >= 1
    for item in own["items"]:
        assert item["company_id"] == tenant_a["company_id"]
    # B's list never contains A's company_id.
    other = clients.get("/revenue", headers=tenant_b["headers"]).json()
    for item in other["items"]:
        assert item["company_id"] == tenant_b["company_id"]
