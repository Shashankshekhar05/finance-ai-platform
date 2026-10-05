"""Database health probing (read-only).

Checks: (1) the server answers, (2) the pgvector extension is installed.
Returns a safe dataclass — never a DSN, traceback, or driver internals.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class DatabaseHealth:
    reachable: bool
    pgvector: bool
    detail: str


def check_database(session: Session) -> DatabaseHealth:
    try:
        session.execute(text("SELECT 1"))
        row = session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).first()
        if row is None:
            return DatabaseHealth(
                reachable=True, pgvector=False, detail="pgvector extension missing"
            )
        return DatabaseHealth(reachable=True, pgvector=True, detail="ok")
    except SQLAlchemyError:
        # Intentionally only a static string: safe for clients/logs.
        return DatabaseHealth(reachable=False, pgvector=False, detail="unreachable")
