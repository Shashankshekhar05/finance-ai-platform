# Backend — production image (Phase 11: Supabase deployment target).
#
# Principles (AGENTS.md §10, §13):
# - No secrets baked in: DATABASE_URL / JWT_SECRET_KEY / GROQ_API_KEY arrive
#   as environment at runtime, never as build args.
# - No migrations at startup: run `alembic upgrade head` as a separate
#   deploy job against the DIRECT Supabase connection (port 5432).
# - Non-root execution; production uvicorn (no --reload).

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

# libgomp1: OpenMP runtime required by torch (sentence-transformers).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /srv/app/storage/documents \
    && chown -R appuser:appuser /srv/app

USER appuser

EXPOSE 8000

# ${PORT:-8000}: honors the host platform's injected port (Render/Fly/etc.).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
