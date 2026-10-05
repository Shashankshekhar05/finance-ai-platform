"""Deterministic finance fixtures for calculation tests (§39).

Company A: R1 2024Q4=1000, R2 2025Q4=1200 (both North/Software/License),
R3 2025Q4=400 (South/Services/Support), E1 2025Q4=300 (Operations/Eng/North),
3 transactions. Company B: R4 2025Q4=9000000 (isolation counterweight).
Fixed values, no randomness. Seeded over HTTP (analyst role).
"""

from fastapi.testclient import TestClient


def _post(client: TestClient, headers: dict, path: str, body: dict) -> dict:
    response = client.post(path, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def seed_company_a(client: TestClient, headers: dict) -> None:
    _post(
        client,
        headers,
        "/revenue",
        {
            "amount": "1000.00",
            "currency": "USD",
            "record_date": "2024-10-15",
            "fiscal_year": 2024,
            "fiscal_quarter": 4,
            "segment": "Software",
            "region": "North",
            "category": "License",
        },
    )
    _post(
        client,
        headers,
        "/revenue",
        {
            "amount": "1200.00",
            "currency": "USD",
            "record_date": "2025-10-15",
            "fiscal_year": 2025,
            "fiscal_quarter": 4,
            "segment": "Software",
            "region": "North",
            "category": "License",
        },
    )
    _post(
        client,
        headers,
        "/revenue",
        {
            "amount": "400.00",
            "currency": "USD",
            "record_date": "2025-11-20",
            "fiscal_year": 2025,
            "fiscal_quarter": 4,
            "segment": "Services",
            "region": "South",
            "category": "Support",
        },
    )
    _post(
        client,
        headers,
        "/expenses",
        {
            "amount": "300.00",
            "currency": "USD",
            "record_date": "2025-10-20",
            "fiscal_year": 2025,
            "fiscal_quarter": 4,
            "category": "Operations",
            "department": "Eng",
            "region": "North",
        },
    )
    _post(
        client,
        headers,
        "/transactions",
        {
            "occurred_at": "2025-01-05T10:00:00Z",
            "amount": "500.00",
            "currency": "USD",
            "type": "income",
            "category": "Sales",
            "account": "Operating",
        },
    )
    _post(
        client,
        headers,
        "/transactions",
        {
            "occurred_at": "2025-02-05T10:00:00Z",
            "amount": "100.00",
            "currency": "USD",
            "type": "expense",
            "category": "Travel",
            "account": "Operating",
        },
    )
    _post(
        client,
        headers,
        "/transactions",
        {
            "occurred_at": "2025-03-05T10:00:00Z",
            "amount": "50.00",
            "currency": "USD",
            "type": "transfer",
            "category": "Internal",
            "account": "Savings",
        },
    )


def seed_company_b(client: TestClient, headers: dict) -> None:
    _post(
        client,
        headers,
        "/revenue",
        {
            "amount": "9000000.00",
            "currency": "USD",
            "record_date": "2025-10-15",
            "fiscal_year": 2025,
            "fiscal_quarter": 4,
            "segment": "Software",
            "region": "South",
            "category": "License",
        },
    )
