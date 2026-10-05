"""Health routes. Thin by rule: no SQL, no engine creation, no math.

- GET /health      liveness, no database involved.
- GET /health/db readiness: SELECT 1 + pgvector presence; 503 when down.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.health import check_database

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
def health_db(response: Response, session: Session = Depends(get_db)) -> dict[str, str]:
    result = check_database(session)
    if not result.reachable:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "unavailable"}
    if not result.pgvector:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "ok", "pgvector": "missing"}
    return {"status": "ok", "database": "ok", "pgvector": "ok"}
