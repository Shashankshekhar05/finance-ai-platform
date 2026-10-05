"""Session lifecycle: commit/rollback/close through OUR helpers."""

from unittest import mock

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.db.engine import create_engine_for, dispose_engine, get_db, session_scope
from tests.conftest import is_database_reachable


@pytest.fixture()
def memory_engine() -> Engine:
    engine = create_engine_for("sqlite://")
    try:
        yield engine
    finally:
        engine.dispose()


def test_session_scope_commits_and_closes(memory_engine: Engine) -> None:
    with (
        mock.patch.object(Session, "commit", autospec=True) as m_commit,
        mock.patch.object(Session, "rollback", autospec=True) as m_rollback,
        mock.patch.object(Session, "close", autospec=True) as m_close,
    ):
        with session_scope(memory_engine) as session:
            assert session.execute(text("SELECT 1")).scalar() == 1
        assert m_commit.call_count == 1
        assert m_rollback.call_count == 0
        assert m_close.call_count == 1


def test_session_scope_rolls_back_and_closes_on_error(memory_engine: Engine) -> None:
    with (
        mock.patch.object(Session, "commit", autospec=True) as m_commit,
        mock.patch.object(Session, "rollback", autospec=True) as m_rollback,
        mock.patch.object(Session, "close", autospec=True) as m_close,
    ):
        with pytest.raises(RuntimeError, match="boom"):
            with session_scope(memory_engine) as session:
                session.execute(text("SELECT 1"))
                raise RuntimeError("boom")
        assert m_commit.call_count == 0
        assert m_rollback.call_count == 1
        assert m_close.call_count == 1


def test_session_scope_transaction_semantics(memory_engine: Engine) -> None:
    """Real sessions: commit persists, error discards, engine stays usable."""
    with session_scope(memory_engine) as session:
        session.execute(text("CREATE TABLE probe (id INTEGER PRIMARY KEY, v TEXT)"))
        session.execute(text("INSERT INTO probe (v) VALUES ('a')"))
    with pytest.raises(RuntimeError, match="boom"):
        with session_scope(memory_engine) as session:
            session.execute(text("INSERT INTO probe (v) VALUES ('b')"))
            raise RuntimeError("boom")
    with session_scope(memory_engine) as session:
        assert session.execute(text("SELECT COUNT(*) FROM probe")).scalar() == 1


@pytest.mark.integration
def test_get_db_yields_working_session_and_closes() -> None:
    """Drive the real FastAPI dependency generator (live DB)."""
    if not is_database_reachable():
        pytest.skip("PostgreSQL not reachable at DATABASE_URL")
    try:
        with mock.patch.object(Session, "close", autospec=True) as m_close:
            gen = get_db()
            session = next(gen)
            assert session.execute(text("SELECT 1")).scalar() == 1
            with pytest.raises(StopIteration):
                next(gen)
            assert m_close.call_count == 1
    finally:
        dispose_engine()


@pytest.mark.integration
def test_get_db_rolls_back_and_closes_on_error() -> None:
    """An exception inside the request rolls back and still closes."""
    if not is_database_reachable():
        pytest.skip("PostgreSQL not reachable at DATABASE_URL")
    try:
        with (
            mock.patch.object(Session, "rollback", autospec=True) as m_rollback,
            mock.patch.object(Session, "close", autospec=True) as m_close,
        ):
            gen = get_db()
            next(gen)
            with pytest.raises(RuntimeError, match="boom"):
                gen.throw(RuntimeError("boom"))
            assert m_rollback.call_count == 1
            assert m_close.call_count == 1
    finally:
        dispose_engine()
