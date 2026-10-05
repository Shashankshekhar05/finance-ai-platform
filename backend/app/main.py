"""FastAPI application factory.

Phase 3: health + auth + finance routers. No `create_all`, no RAG wiring —
those arrive in later phases.
"""

import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.ai import router as ai_router
from app.api.routes.ai_query import router as ai_query_router
from app.api.routes.auth import router as auth_router
from app.api.routes.calculations import router as calculations_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.documents import router as documents_router
from app.api.routes.expenses import router as expenses_router
from app.api.routes.retrieval import router as retrieval_router
from app.api.routes.financial_metrics import router as metrics_router
from app.api.routes.health import router as health_router
from app.api.routes.revenue import router as revenue_router
from app.api.routes.transactions import router as transactions_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.db.engine import dispose_engine

import app.models  # noqa: F401 — register ORM mappers at startup

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # Phase 11: cross-origin production (frontend and backend on different
    # origins). Explicit allowlist only — never "*" with credentials. Empty
    # (local default) means no CORS middleware; the same-origin Next.js
    # rewrite proxy covers local development.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=600,
        )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(ai_router)
    app.include_router(ai_query_router)
    app.include_router(calculations_router)
    app.include_router(conversations_router)
    app.include_router(documents_router)
    app.include_router(retrieval_router)
    app.include_router(revenue_router)
    app.include_router(expenses_router)
    app.include_router(transactions_router)
    app.include_router(metrics_router)
    return app


app = create_app()
