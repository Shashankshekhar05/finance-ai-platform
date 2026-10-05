"""Finance authorization matrix: viewer reads, analyst writes, admin deletes.

One parametrized matrix per verb across all three writable resources, plus
metrics read-only rules (GET allowed, POST/DELETE are 405, not 403).
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import is_database_reachable, tenant_who
from tests.test_finance_crud import EXPENSE_BODY, REVENUE_BODY, TRANSACTION_BODY

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)

RESOURCES = [
    ("/revenue", REVENUE_BODY, {"segment": "Matrix"}),
    ("/expenses", EXPENSE_BODY, {"vendor": "Matrix"}),
    ("/transactions", TRANSACTION_BODY, {"description": "Matrix"}),
]


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def users(clients: TestClient) -> dict[str, dict]:
    return {
        "viewer": tenant_who(clients, role="viewer"),
        "analyst": tenant_who(clients, role="analyst"),
        "admin": tenant_who(clients, role="admin"),
    }


@pytest.fixture(scope="module")
def seed_ids(users: dict[str, dict]) -> dict[str, dict[str, str]]:
    """One row per resource in EACH role's own company (service-seeded, so
    viewer-owned rows exist without granting write over HTTP)."""
    import uuid as uuid_lib

    from app.db.engine import dispose_engine, get_engine, session_scope
    from app.schemas.expense import ExpenseCreate
    from app.schemas.revenue import RevenueCreate
    from app.schemas.transaction import TransactionCreate
    from app.services import expense_service, revenue_service, transaction_service

    out: dict[str, dict[str, str]] = {}
    for role, user in users.items():
        cid = uuid_lib.UUID(user["company_id"])
        engine = get_engine()
        try:
            with session_scope(engine) as session:
                revenue = revenue_service.create_revenue(
                    session, company_id=cid, data=RevenueCreate(**REVENUE_BODY)
                )
                expense = expense_service.create_expense(
                    session, company_id=cid, data=ExpenseCreate(**EXPENSE_BODY)
                )
                transaction = transaction_service.create_transaction(
                    session, company_id=cid, data=TransactionCreate(**TRANSACTION_BODY)
                )
        finally:
            dispose_engine()
        out[role] = {
            "/revenue": str(revenue.id),
            "/expenses": str(expense.id),
            "/transactions": str(transaction.id),
        }
    return out


def _status(response) -> int:  # type: ignore[no-untyped-def]
    return response.status_code


@pytest.mark.parametrize("path,body,patch", RESOURCES)
def test_viewer_read_only(
    clients: TestClient,
    users: dict[str, dict],
    seed_ids: dict[str, dict[str, str]],
    path: str,
    body: dict,
    patch: dict,
) -> None:
    headers = users["viewer"]["headers"]
    own_id = seed_ids["viewer"][path]
    assert _status(clients.get(path, headers=headers)) == 200
    assert _status(clients.get(f"{path}/{own_id}", headers=headers)) == 200
    assert _status(clients.post(path, json=body, headers=headers)) == 403
    assert (
        _status(clients.patch(f"{path}/{own_id}", json=patch, headers=headers)) == 403
    )
    assert _status(clients.delete(f"{path}/{own_id}", headers=headers)) == 403
    assert clients.post(path, json=body, headers=headers).json()["error"]["code"] == (
        "insufficient_permissions"
    )


@pytest.mark.parametrize("path,body,patch", RESOURCES)
def test_analyst_cannot_delete(
    clients: TestClient,
    users: dict[str, dict],
    seed_ids: dict[str, dict[str, str]],
    path: str,
    body: dict,
    patch: dict,
) -> None:
    headers = users["analyst"]["headers"]
    own_id = seed_ids["analyst"][path]
    assert _status(clients.get(path, headers=headers)) == 200
    created = clients.post(path, json=body, headers=headers)
    assert _status(created) == 201
    assert (
        _status(
            clients.patch(f"{path}/{created.json()['id']}", json=patch, headers=headers)
        )
        == 200
    )
    denied = clients.delete(f"{path}/{own_id}", headers=headers)
    assert _status(denied) == 403
    assert denied.json()["error"]["code"] == "insufficient_permissions"


@pytest.mark.parametrize("path,body,patch", RESOURCES)
def test_admin_full_access(
    clients: TestClient, users: dict[str, dict], path: str, body: dict, patch: dict
) -> None:
    headers = users["admin"]["headers"]
    assert _status(clients.get(path, headers=headers)) == 200
    created = clients.post(path, json=body, headers=headers)
    assert _status(created) == 201
    rid = created.json()["id"]
    assert _status(clients.patch(f"{path}/{rid}", json=patch, headers=headers)) == 200
    assert _status(clients.delete(f"{path}/{rid}", headers=headers)) == 204
    assert _status(clients.get(f"{path}/{rid}", headers=headers)) == 404


def test_metrics_read_only_for_all_roles(
    clients: TestClient, users: dict[str, dict]
) -> None:
    for role in ("viewer", "analyst", "admin"):
        response = clients.get("/financial-metrics", headers=users[role]["headers"])
        assert response.status_code == 200, (role, response.text)
    # No write verbs exist: 405 with the shared envelope, not 403/404.
    for method in ("post", "patch", "delete"):
        response = clients.request(
            method, "/financial-metrics", headers=users["admin"]["headers"]
        )
        assert response.status_code == 405, (method, response.text)
        assert response.json()["error"]["code"] == "method_not_allowed"


def test_unauthenticated_finance_requests_rejected(clients: TestClient) -> None:
    for path in ("/revenue", "/expenses", "/transactions", "/financial-metrics"):
        response = clients.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "authentication_required"
