"""SQLAlchemy 2.x engine + session infrastructure.

Boundaries (see DEVELOPMENT_RULES.md §2, DATABASE_RULES.md §7A):
- This module owns engines and session lifecycle. Nothing else creates engines.
- Routes/services NEVER create engines; they receive sessions via `get_db`.
- No global manually-managed *sessions*. Exactly one lazily-created shared
  *engine* lives here, disposed on application shutdown.
- SQLite branch exists only so session mechanics stay unit-testable without
  a server; the production path is always PostgreSQL.
"""

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

_engine: Engine | None = None
_engine_url: str | None = None


def create_engine_for(
    database_url: str, *, pool_size: int = 5, max_overflow: int = 10
) -> Engine:
    """Build a new engine for a URL. Pure function: no global state.

    Pool defaults are the historic production values; callers (get_engine)
    pass the Settings overrides. `pool_pre_ping` stays always-on so stale
    managed-PostgreSQL (Supabase) connections fail fast instead of serving
    half-open checkouts.
    """
    if database_url.startswith("sqlite:"):
        # Test-only path: default SQLite pooling (no pool_size args).
        return create_engine(database_url)
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )


def get_engine(settings: Settings | None = None) -> Engine:
    """Return the shared engine, creating it once per database URL."""
    global _engine, _engine_url
    resolved = settings or get_settings()
    url = str(resolved.database_url)
    if _engine is None or _engine_url != url:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine_for(
            url,
            pool_size=resolved.db_pool_size,
            max_overflow=resolved.db_pool_max_overflow,
        )
        _engine_url = url
    return _engine


def dispose_engine() -> None:
    """Dispose the shared engine. Called on app shutdown and in tests."""
    global _engine, _engine_url
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _engine_url = None


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    session = get_session_factory(get_engine())()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Transactional scope for workers/tests: commit or rollback, always close."""
    session = get_session_factory(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
