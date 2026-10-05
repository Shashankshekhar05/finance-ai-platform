"""Calculation API: ops matrix, filters, grouping, comparisons, tenancy.

Module tenants: analyst_a/viewer_a (company A, seeded), analyst_b
(company B, counterweight). Exact string assertions throughout — no floats.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.calc_factories import seed_company_a, seed_company_b
from tests.conftest import is_database_reachable, tenant_who

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def analyst_a(clients: TestClient) -> dict:
    user = tenant_who(clients, role="analyst")
    seed_company_a(clients, user["headers"])
    return user


@pytest.fixture(scope="module")
def viewer_a(clients: TestClient) -> dict:
    return tenant_who(clients, role="viewer")


@pytest.fixture(scope="module")
def analyst_b(clients: TestClient) -> dict:
    user = tenant_who(clients, role="analyst")
    seed_company_b(clients, user["headers"])
    return user


def _calc(clients: TestClient, headers: dict, body: dict):
    return clients.post("/calculations", json=body, headers=headers)


def _envelope(response, *, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text


def test_basic_ops(clients: TestClient, analyst_a: dict) -> None:
    headers = analyst_a["headers"]
    cases = [
        ({"dataset": "revenue", "operation": "sum"}, "2600.00", "money"),
        ({"dataset": "revenue", "operation": "count"}, "3", "count"),
        ({"dataset": "revenue", "operation": "average"}, "866.67", "money"),
        ({"dataset": "revenue", "operation": "minimum"}, "400.00", "money"),
        ({"dataset": "revenue", "operation": "maximum"}, "1200.00", "money"),
        ({"dataset": "expense", "operation": "sum"}, "300.00", "money"),
        ({"dataset": "transaction", "operation": "sum"}, "650.00", "money"),
        ({"dataset": "transaction", "operation": "count"}, "3", "count"),
    ]
    for body, expected, unit in cases:
        response = _calc(clients, headers, body)
        assert response.status_code == 200, (body, response.text)
        result = response.json()
        assert result["kind"] == "single"
        assert result["value"] == expected, body
        assert result["unit"] == unit
        assert result["has_data"] is True and result["status"] == "ok"
        assert result["record_count"] >= 1
        assert result["provenance"]["company_id"] == analyst_a["company_id"]
        assert result["provenance"]["source_type"] == "structured_finance"


def test_filters(clients: TestClient, analyst_a: dict) -> None:
    headers = analyst_a["headers"]
    cases = [
        ({"filters": {"fiscal_year": 2025}}, "1600.00"),
        ({"filters": {"fiscal_year": 2025, "quarter": 4}}, "1600.00"),
        ({"filters": {"region": "North"}}, "2200.00"),
        ({"filters": {"region": "South"}}, "400.00"),
        ({"filters": {"segment": "Software"}}, "2200.00"),
        ({"filters": {"category": "License"}}, "2200.00"),
        ({"filters": {"date_from": "2025-10-15", "date_to": "2025-10-15"}}, "1200.00"),
        ({"filters": {"currency": "USD"}}, "2600.00"),
    ]
    for partial, expected in cases:
        body = {"dataset": "revenue", "operation": "sum", **partial}
        assert _calc(clients, headers, body).json()["value"] == expected, partial
    expense = _calc(
        clients,
        headers,
        {
            "dataset": "expense",
            "operation": "sum",
            "filters": {"department": "Eng", "vendor": None, "category": "Operations"},
        },
    ).json()
    assert expense["value"] == "300.00"
    txn = _calc(
        clients,
        headers,
        {
            "dataset": "transaction",
            "operation": "sum",
            "filters": {"transaction_type": "income"},
        },
    ).json()
    assert txn["value"] == "500.00"


def test_invalid_filters_rejected(clients: TestClient, analyst_a: dict) -> None:
    headers = analyst_a["headers"]
    _envelope(
        _calc(
            clients,
            headers,
            {
                "dataset": "revenue",
                "operation": "sum",
                "filters": {"department": "Eng"},
            },
        ),
        status=422,
        code="invalid_filter",
    )
    _envelope(
        _calc(
            clients,
            headers,
            {"dataset": "revenue", "operation": "sum", "filters": {"quarter": 4}},
        ),
        status=422,
        code="validation_error",  # schema-level quarter rule
    )
    _envelope(
        _calc(
            clients,
            headers,
            {
                "dataset": "revenue",
                "operation": "sum",
                "filters": {"date_from": "2025-02-01", "date_to": "2025-01-01"},
            },
        ),
        status=422,
        code="validation_error",
    )
    _envelope(
        _calc(
            clients,
            headers,
            {"dataset": "revenue", "operation": "sum", "group_by": ["vendor"]},
        ),
        status=422,
        code="invalid_group_by",
    )
    _envelope(
        _calc(
            clients,
            headers,
            {"dataset": "revenue", "operation": "sum", "group_by": ["region", "oops"]},
        ),
        status=422,
        code="invalid_group_by",
    )
    # Smuggled tenant scope is not a field at all.
    _envelope(
        _calc(
            clients,
            headers,
            {"dataset": "revenue", "operation": "sum", "company_id": "x"},
        ),
        status=422,
        code="validation_error",
    )


def test_grouping(clients: TestClient, analyst_a: dict) -> None:
    headers = analyst_a["headers"]
    one = _calc(
        clients,
        headers,
        {"dataset": "revenue", "operation": "sum", "group_by": ["region"]},
    ).json()
    assert one["kind"] == "grouped"
    assert one["status"] == "ok"
    assert {g["dimensions"]["region"]: g["value"] for g in one["groups"]} == {
        "North": "2200.00",
        "South": "400.00",
    }
    assert [g["dimensions"]["region"] for g in one["groups"]] == ["North", "South"]
    assert all(g["record_count"] >= 1 for g in one["groups"])
    assert one["record_count"] == 3

    two = _calc(
        clients,
        headers,
        {"dataset": "revenue", "operation": "sum", "group_by": ["region", "segment"]},
    ).json()
    dims = {
        (g["dimensions"]["region"], g["dimensions"]["segment"]): g["value"]
        for g in two["groups"]
    }
    assert dims == {("North", "Software"): "2200.00", ("South", "Services"): "400.00"}

    counted = _calc(
        clients,
        headers,
        {"dataset": "expense", "operation": "count", "group_by": ["category"]},
    ).json()
    assert counted["groups"][0]["value"] == "1"
    assert counted["unit"] == "count"

    # Grouped average/minimum are not supported (sum/count shape only).
    _envelope(
        _calc(
            clients,
            headers,
            {"dataset": "revenue", "operation": "average", "group_by": ["region"]},
        ),
        status=422,
        code="unsupported_calculation",
    )


def test_growth(clients: TestClient, analyst_a: dict) -> None:
    headers = analyst_a["headers"]
    explicit = _calc(
        clients,
        headers,
        {
            "dataset": "revenue",
            "operation": "growth_rate",
            "current_period": {"fiscal_year": 2025, "quarter": 4},
            "comparison_period": {"fiscal_year": 2024, "quarter": 4},
        },
    ).json()
    assert explicit["kind"] == "comparison"
    assert explicit["current_value"] == "1600.00"
    assert explicit["comparison_value"] == "1000.00"
    assert explicit["percent_value"] == "60.00"
    assert explicit["unit"] == "percent" and explicit["status"] == "ok"

    auto = _calc(
        clients,
        headers,
        {
            "dataset": "revenue",
            "operation": "growth_rate",
            "current_period": {"fiscal_year": 2025, "quarter": 4},
        },
    ).json()
    assert auto["comparison_period"] == {"fiscal_year": 2024, "quarter": 4}
    assert auto["percent_value"] == "60.00"

    north = _calc(
        clients,
        headers,
        {
            "dataset": "revenue",
            "operation": "growth_rate",
            "filters": {"region": "North"},
            "current_period": {"fiscal_year": 2025, "quarter": 4},
            "comparison_period": {"fiscal_year": 2024, "quarter": 4},
        },
    ).json()
    assert north["percent_value"] == "20.00"

    nodata = _calc(
        clients,
        headers,
        {
            "dataset": "revenue",
            "operation": "growth_rate",
            "current_period": {"fiscal_year": 1999},
            "comparison_period": {"fiscal_year": 1998},
        },
    ).json()
    assert nodata["status"] == "no_data" and nodata["has_data"] is False

    _envelope(
        _calc(clients, headers, {"dataset": "revenue", "operation": "growth_rate"}),
        status=422,
        code="invalid_period",  # current period required
    )
    _envelope(
        _calc(
            clients,
            headers,
            {
                "dataset": "revenue",
                "operation": "growth_rate",
                "filters": {"fiscal_year": 2025},
                "current_period": {"fiscal_year": 2025},
            },
        ),
        status=422,
        code="invalid_period",  # fiscal scope must come from the period
    )


def test_variance(clients: TestClient, analyst_a: dict) -> None:
    headers = analyst_a["headers"]
    result = _calc(
        clients,
        headers,
        {
            "dataset": "revenue",
            "operation": "variance",
            "current_period": {"fiscal_year": 2025},
            "comparison_period": {"fiscal_year": 2024},
        },
    ).json()
    assert result["current_value"] == "1600.00"
    assert result["comparison_value"] == "1000.00"
    assert result["absolute_variance"] == "600.00"
    assert result["percent_value"] == "60.00"
    assert result["status"] == "ok"


def test_margin(clients: TestClient, analyst_a: dict) -> None:
    headers = analyst_a["headers"]
    result = _calc(
        clients,
        headers,
        {
            "dataset": "revenue",
            "operation": "margin",
            "filters": {"fiscal_year": 2025, "region": "North"},
        },
    ).json()
    assert result["kind"] == "margin"
    assert result["revenue_value"] == "1200.00"
    assert result["expense_value"] == "300.00"
    assert result["absolute_value"] == "900.00"
    assert result["margin_percent"] == "75.00"
    assert result["status"] == "ok" and result["has_data"] is True

    nodata = _calc(
        clients,
        headers,
        {"dataset": "revenue", "operation": "margin", "filters": {"fiscal_year": 1999}},
    ).json()
    assert nodata["status"] == "no_data" and nodata["margin_percent"] is None

    _envelope(
        _calc(clients, headers, {"dataset": "expense", "operation": "margin"}),
        status=422,
        code="unsupported_calculation",  # margin anchors on revenue
    )
    _envelope(
        _calc(
            clients,
            headers,
            {
                "dataset": "revenue",
                "operation": "margin",
                "filters": {"department": "Eng"},
            },
        ),
        status=422,
        code="invalid_filter",
    )


def test_no_data_vs_zero(clients: TestClient, analyst_a: dict) -> None:
    headers = analyst_a["headers"]
    empty = _calc(
        clients,
        headers,
        {"dataset": "revenue", "operation": "sum", "filters": {"fiscal_year": 1999}},
    ).json()
    assert empty["value"] is None and empty["has_data"] is False
    assert empty["status"] == "no_data" and empty["record_count"] == 0
    zero_count = _calc(
        clients,
        headers,
        {"dataset": "revenue", "operation": "count", "filters": {"fiscal_year": 1999}},
    ).json()
    assert zero_count["value"] == "0" and zero_count["has_data"] is True


def test_mixed_currency_refused(clients: TestClient, analyst_a: dict) -> None:
    headers = analyst_a["headers"]
    created = clients.post(
        "/revenue",
        json={"amount": "10.00", "currency": "EUR", "record_date": "2025-06-01"},
        headers=headers,
    )
    assert created.status_code == 201
    try:
        _envelope(
            _calc(clients, headers, {"dataset": "revenue", "operation": "sum"}),
            status=422,
            code="mixed_currency",
        )
        scoped = _calc(
            clients,
            headers,
            {"dataset": "revenue", "operation": "sum", "filters": {"currency": "USD"}},
        ).json()
        assert scoped["value"] == "2600.00"
    finally:
        # Remove the EUR row so later tests see a single-currency company.
        from app.db.engine import dispose_engine, get_engine, session_scope

        import uuid as uuid_lib
        from app.repositories import revenue_repository

        engine = get_engine()
        try:
            with session_scope(engine) as session:
                record = revenue_repository.get(
                    session,
                    company_id=uuid_lib.UUID(analyst_a["company_id"]),
                    revenue_id=uuid_lib.UUID(created.json()["id"]),
                )
                assert record is not None
                revenue_repository.delete(session, record=record)
        finally:
            dispose_engine()


def test_tenant_leak_exact(
    clients: TestClient, analyst_a: dict, analyst_b: dict
) -> None:
    """§38 scenario: A=1000+1200+400, B=9000000. A must see 2600, never more."""
    headers_a, headers_b = analyst_a["headers"], analyst_b["headers"]
    assert (
        _calc(
            clients,
            headers_a,
            {
                "dataset": "revenue",
                "operation": "sum",
                "filters": {"fiscal_year": 2025},
            },
        ).json()["value"]
        == "1600.00"
    )
    assert (
        _calc(
            clients,
            headers_b,
            {
                "dataset": "revenue",
                "operation": "sum",
                "filters": {"fiscal_year": 2025},
            },
        ).json()["value"]
        == "9000000.00"
    )
    grouped = _calc(
        clients,
        headers_a,
        {
            "dataset": "revenue",
            "operation": "sum",
            "filters": {"fiscal_year": 2025},
            "group_by": ["region"],
        },
    ).json()
    assert {g["dimensions"]["region"]: g["value"] for g in grouped["groups"]} == {
        "North": "1200.00",
        "South": "400.00",
    }
    growth = _calc(
        clients,
        headers_a,
        {
            "dataset": "revenue",
            "operation": "growth_rate",
            "filters": {"region": "South"},
            "current_period": {"fiscal_year": 2025},
            "comparison_period": {"fiscal_year": 2024},
        },
    ).json()
    assert growth["current_value"] == "400.00"
    assert growth["status"] == "no_data"  # B's South millions must not appear


def test_roles_and_anonymous(clients: TestClient, analyst_a: dict) -> None:
    from tests.conftest import tenant_who

    viewer = tenant_who(clients, role="viewer")
    admin = tenant_who(clients, role="admin")
    body = {"dataset": "revenue", "operation": "count"}
    for user in (viewer, analyst_a, admin):
        response = _calc(clients, user["headers"], body)
        assert response.status_code == 200, user
    anonymous = clients.post("/calculations", json=body)
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "authentication_required"
