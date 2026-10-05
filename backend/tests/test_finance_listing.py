"""Finance listing: pagination, filtering, sorting — deterministic and bounded."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import is_database_reachable, tenant_who

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def analyst(clients: TestClient) -> dict:
    user = tenant_who(clients, role="analyst")
    seed = [
        ("2025-01-05", "EMEA", "Enterprise", "100.00"),
        ("2025-02-10", "APAC", "SMB", "200.00"),
        ("2025-03-15", "EMEA", "SMB", "300.00"),
    ]
    for date, region, segment, amount in seed:
        response = clients.post(
            "/revenue",
            json={
                "amount": amount,
                "currency": "USD",
                "record_date": date,
                "region": region,
                "segment": segment,
            },
            headers=user["headers"],
        )
        assert response.status_code == 201, response.text
    for i, category in enumerate(["Travel", "Travel", "Infra"]):
        response = clients.post(
            "/expenses",
            json={
                "amount": f"{10 + i}.00",
                "currency": "USD",
                "record_date": f"2025-0{i + 1}-01",
                "category": category,
            },
            headers=user["headers"],
        )
        assert response.status_code == 201, response.text
    return user


def test_pagination_bounds_and_envelope(clients: TestClient, analyst: dict) -> None:
    first = clients.get(
        "/revenue", params={"limit": 2, "offset": 0}, headers=analyst["headers"]
    ).json()
    assert first["limit"] == 2 and first["offset"] == 0
    assert first["total"] >= 3 and len(first["items"]) == 2
    second = clients.get(
        "/revenue", params={"limit": 2, "offset": 2}, headers=analyst["headers"]
    ).json()
    assert len(second["items"]) == second["total"] - 2
    assert {item["id"] for item in first["items"]}.isdisjoint(
        {item["id"] for item in second["items"]}
    )
    # Over-large pages rejected; unknown sort rejected; bad order rejected.
    assert (
        clients.get(
            "/revenue", params={"limit": 201}, headers=analyst["headers"]
        ).status_code
        == 422
    )
    assert (
        clients.get(
            "/revenue", params={"sort": "company_id"}, headers=analyst["headers"]
        ).status_code
        == 422
    )
    assert (
        clients.get(
            "/revenue", params={"order": "sideways"}, headers=analyst["headers"]
        ).status_code
        == 422
    )


def test_revenue_filtering(clients: TestClient, analyst: dict) -> None:
    headers = analyst["headers"]
    emea = clients.get("/revenue", params={"region": "EMEA"}, headers=headers).json()
    assert emea["total"] >= 2
    assert all(item["region"] == "EMEA" for item in emea["items"])
    smb = clients.get("/revenue", params={"segment": "SMB"}, headers=headers).json()
    assert all(item["segment"] == "SMB" for item in smb["items"])
    ranged = clients.get(
        "/revenue",
        params={"date_from": "2025-02-01", "date_to": "2025-02-28"},
        headers=headers,
    ).json()
    assert ranged["total"] >= 1
    assert all(
        "2025-02-01" <= item["record_date"] <= "2025-02-28" for item in ranged["items"]
    )
    fiscal = clients.get(
        "/revenue", params={"fiscal_year": 1999}, headers=headers
    ).json()
    assert fiscal["total"] == 0 and fiscal["items"] == []


def test_expense_filtering(clients: TestClient, analyst: dict) -> None:
    travel = clients.get(
        "/expenses", params={"category": "Travel"}, headers=analyst["headers"]
    ).json()
    assert travel["total"] >= 2
    assert all(item["category"] == "Travel" for item in travel["items"])


def test_sorting_is_allowlisted_and_deterministic(
    clients: TestClient, analyst: dict
) -> None:
    headers = analyst["headers"]
    desc = clients.get(
        "/revenue", params={"sort": "amount", "order": "desc"}, headers=headers
    ).json()
    amounts = [item["amount"] for item in desc["items"]]
    assert amounts == sorted(amounts, reverse=True)
    asc = clients.get(
        "/revenue", params={"sort": "amount", "order": "asc"}, headers=headers
    ).json()
    assert [item["amount"] for item in asc["items"]] == sorted(
        [item["amount"] for item in asc["items"]]
    )
    # Same query twice → identical order (id tiebreaker).
    again = clients.get(
        "/revenue", params={"sort": "amount", "order": "desc"}, headers=headers
    ).json()
    assert [item["id"] for item in again["items"]] == [
        item["id"] for item in desc["items"]
    ]
