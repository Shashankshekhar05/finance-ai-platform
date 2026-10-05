"""Readiness endpoint: asserts shape + status in both DB states."""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.db.engine import create_engine_for, get_session_factory
from app.main import create_app
from tests.conftest import is_database_reachable


@pytest.mark.integration
def test_health_db(client: TestClient) -> None:
    response = client.get("/health/db")
    body = response.json()
    if is_database_reachable():
        assert response.status_code == 200
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        assert body["pgvector"] == "ok"
    else:
        assert response.status_code == 503
        assert body == {"status": "degraded", "database": "unavailable"}


def test_health_db_reports_503_when_database_down() -> None:
    """503 branch, permanently covered: dependency overridden to a dead URL."""
    bad_engine = create_engine_for("postgresql+psycopg2://u:p@127.0.0.1:1/db")
    try:

        def _unreachable_db():  # type: ignore[no-untyped-def]
            session = get_session_factory(bad_engine)()
            try:
                yield session
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        app = create_app()
        app.dependency_overrides[get_db] = _unreachable_db
        response = TestClient(app).get("/health/db")
        assert response.status_code == 503
        assert response.json() == {"status": "degraded", "database": "unavailable"}
    finally:
        bad_engine.dispose()
