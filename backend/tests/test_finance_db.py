"""Finance database behavior: constraints, decimals, keys, metric upsert.

Proves the guarantees the API layer relies on: exact numerics, CHECKs,
foreign keys with RESTRICT (money is never cascade-deleted), and the
(single) business unique on metrics with recompute-upsert semantics.
"""

import datetime
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db.engine import dispose_engine, get_engine, session_scope
from app.main import create_app
from app.models.expense import Expense
from app.models.revenue import Revenue
from app.schemas.financial_metric import MetricRecordInput
from app.services import metric_service
from tests.conftest import is_database_reachable, register_user, unique_email

pytestmark = pytest.mark.skipif(
    not is_database_reachable(), reason="PostgreSQL not reachable at DATABASE_URL"
)


@pytest.fixture(scope="module")
def clients() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def company_id(clients: TestClient) -> uuid.UUID:
    user = register_user(clients, email=unique_email("findb"))
    return uuid.UUID(user["companies"][0]["company_id"])


def test_decimal_precision_round_trip(company_id: uuid.UUID) -> None:
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            record = Revenue(
                company_id=company_id,
                amount=Decimal("1234.50"),
                currency="USD",
                record_date=datetime.date(2025, 1, 1),
            )
            session.add(record)
        with session_scope(engine) as session:
            from app.repositories import revenue_repository

            fetched = revenue_repository.get(
                session, company_id=company_id, revenue_id=record.id
            )
            assert fetched is not None
            assert fetched.amount == Decimal("1234.50")
            assert str(fetched.amount) == "1234.50"
    finally:
        dispose_engine()


def test_negative_amount_rejected_by_check(company_id: uuid.UUID) -> None:
    engine = get_engine()
    try:
        with pytest.raises(IntegrityError):
            with session_scope(engine) as session:
                session.add(
                    Expense(
                        company_id=company_id,
                        amount=Decimal("-1.00"),
                        currency="USD",
                        record_date=datetime.date(2025, 1, 1),
                        category="Travel",
                    )
                )
    finally:
        dispose_engine()
    # Row must not exist.
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            from sqlalchemy import func, select

            count = session.execute(
                select(func.count())
                .select_from(Expense)
                .where(Expense.company_id == company_id, Expense.amount < 0)
            ).scalar_one()
            assert count == 0
    finally:
        dispose_engine()


def test_quarter_without_year_rejected_by_check(company_id: uuid.UUID) -> None:
    from sqlalchemy import text

    engine = get_engine()
    try:
        with pytest.raises(IntegrityError):
            with session_scope(engine) as session:
                session.execute(
                    text(
                        "INSERT INTO revenue "
                        "(id, company_id, amount, currency, record_date, fiscal_quarter) "
                        "VALUES (gen_random_uuid(), :cid, 10, 'USD', '2025-01-01', 2)"
                    ),
                    {"cid": str(company_id)},
                )
    finally:
        dispose_engine()


def test_company_delete_restricted_while_money_exists(company_id: uuid.UUID) -> None:
    from app.models.company import Company

    engine = get_engine()
    try:
        with session_scope(engine) as session:
            session.add(
                Revenue(
                    company_id=company_id,
                    amount=Decimal("5.00"),
                    currency="USD",
                    record_date=datetime.date(2025, 1, 1),
                )
            )
        with pytest.raises(IntegrityError):
            with session_scope(engine) as session:
                company = session.get(Company, company_id)
                assert company is not None
                session.delete(company)
    finally:
        dispose_engine()


def test_metric_upsert_converges_on_unique(company_id: uuid.UUID) -> None:
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            first = metric_service.record_metric(
                session,
                company_id=company_id,
                data=MetricRecordInput(
                    period=datetime.date(2025, 1, 1),
                    metric_name="net_margin",
                    value="0.10000000",
                    computed_by="reported",
                ),
            )
            second = metric_service.record_metric(
                session,
                company_id=company_id,
                data=MetricRecordInput(
                    period=datetime.date(2025, 1, 1),
                    metric_name="net_margin",
                    value="0.12000000",
                    computed_by="calculated",
                    inputs_ref={"net_income": "12", "revenue": "100"},
                ),
            )
            assert first.id == second.id
            assert str(second.value) == "0.12000000"
    finally:
        dispose_engine()


def test_metric_value_precision_preserved(company_id: uuid.UUID) -> None:
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            read = metric_service.record_metric(
                session,
                company_id=company_id,
                data=MetricRecordInput(
                    period=datetime.date(2025, 2, 1),
                    metric_name="operating_margin",
                    value="0.15234567",
                    computed_by="reported",
                ),
            )
            assert read.value == "0.15234567"
    finally:
        dispose_engine()
