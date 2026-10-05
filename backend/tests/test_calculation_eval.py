"""Calculation evaluation: fixed fixtures, exact expected values (§40).

Uses the §39 fixture companies (seeded in test_calculations) via FRESH
tenants here so this file stands alone. Prints a concise report; asserts
exact Decimal strings. Not a production benchmark — a correctness gate.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.calc_factories import seed_company_a
from tests.conftest import is_database_reachable, tenant_who

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def evaluator(clients: TestClient) -> dict:
    user = tenant_who(clients, role="analyst")
    seed_company_a(clients, user["headers"])
    return user


NORTH_FY25 = {"fiscal_year": 2025, "region": "North"}


def _calc(clients: TestClient, headers: dict, body: dict) -> dict:
    response = clients.post("/calculations", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_calculation_evaluation(
    clients: TestClient, evaluator: dict, capsys: pytest.CaptureFixture
) -> None:
    headers = evaluator["headers"]
    checks: list[tuple[str, str, str]] = []

    revenue = _calc(
        clients,
        headers,
        {"dataset": "revenue", "operation": "sum", "filters": NORTH_FY25},
    )
    checks.append(("Revenue FY2025 (North)", revenue["value"], "1200.00"))

    growth = _calc(
        clients,
        headers,
        {
            "dataset": "revenue",
            "operation": "growth_rate",
            "filters": {"region": "North"},
            "current_period": {"fiscal_year": 2025},
            "comparison_period": {"fiscal_year": 2024},
        },
    )
    checks.append(("YoY growth (North)", growth["percent_value"], "20.00"))

    expense = _calc(
        clients,
        headers,
        {"dataset": "expense", "operation": "sum", "filters": NORTH_FY25},
    )
    checks.append(("Expense FY2025 (North)", expense["value"], "300.00"))

    margin = _calc(
        clients,
        headers,
        {"dataset": "revenue", "operation": "margin", "filters": NORTH_FY25},
    )
    checks.append(("Profit FY2025 (North)", margin["absolute_value"], "900.00"))
    checks.append(("Margin FY2025 (North)", margin["margin_percent"], "75.00"))

    grouped = _calc(
        clients,
        headers,
        {
            "dataset": "revenue",
            "operation": "sum",
            "filters": {"fiscal_year": 2025},
            "group_by": ["region"],
        },
    )
    regions = {g["dimensions"]["region"]: g["value"] for g in grouped["groups"]}
    checks.append(("Grouped North", regions.get("North", ""), "1200.00"))
    checks.append(("Grouped South", regions.get("South", ""), "400.00"))

    with capsys.disabled():
        print("\n=== calculation eval (§40 fixtures) ===")
        for name, actual, expected in checks:
            mark = "PASS" if actual == expected else "FAIL"
            print(f"[{mark}] {name}: got {actual}, expected {expected}")

    for name, actual, expected in checks:
        assert actual == expected, name
