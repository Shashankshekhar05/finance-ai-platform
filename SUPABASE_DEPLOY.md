# SUPABASE_DEPLOY.md — Production Deployment (Phase 11)

> Status: NORMATIVE for deployment. Subordinate to `AGENTS.md`.
> Supabase is a **database/infrastructure target only**: managed PostgreSQL +
> pgvector. It does NOT replace FastAPI, SQLAlchemy, Alembic, backend JWT/RBAC,
> BGE embeddings, or Groq. No frontend → database connection exists anywhere.

Target:

```
Next.js  →  FastAPI  →  SQLAlchemy  →  Supabase PostgreSQL + pgvector
```

No code change is needed to switch databases: only the `DATABASE_URL` value
changes. Verified by `tests/test_deploy_readiness.py` (Supabase URL shapes are
accepted by `Settings` and build a working engine without connecting).

---

## 1. Create the Supabase project

1. Create a new Supabase project (pin a PostgreSQL 15+ version).
2. Note the project reference; you will need two connection strings from
   **Project Settings → Database**:
   - **Direct** connection (port `5432`) — used ONLY for Alembic migrations.
   - **Pooler** connection (port `6543`, transaction mode) — used by the app.

## 2. Enable pgvector

Run against the **direct** connection (Supabase SQL editor is fine for this
one check; schema itself is owned by Alembic, step 6):

```sql
SELECT * FROM pg_extension WHERE extname = 'vector';
```

`0001_enable_pgvector` (`CREATE EXTENSION IF NOT EXISTS vector`) enables it
during `alembic upgrade head`. If your project template already enabled it,
the migration is a harmless no-op.

Compatibility gate (all verified in-repo, no migration rewrite needed):

| Concern | Status |
|---|---|
| UUID PKs (`postgresql.UUID`, app-generated `uuid4`) | No `pgcrypto` needed |
| `timestamptz`, `NUMERIC(18,2)` / `NUMERIC(24,8)`, `JSONB` | Native, no change |
| CHECK constraints, FKs (`RESTRICT`/`CASCADE`), btree indexes | Native, no change |
| `embedding vector(768)` + HNSW `vector_cosine_ops` index | Requires pgvector with HNSW support (0.5+); confirm via `/health/db` after migrate |
| Model/metadata drift | `alembic check` must report clean (step 6) |

Retrieval semantics are frozen: `BAAI/bge-base-en-v1.5`, 768 dims,
L2-normalized both sides, cosine distance (`<=>`), tenant filter
`WHERE company_id = :cid` inside every vector query. Changing any of these
invalidates stored vectors and requires an approved re-embedding migration.

## 3. Obtain the PostgreSQL connection configuration

From Supabase dashboard → Connect → URI. It has the shape
`postgresql://USER:PASSWORD@HOST:PORT/DATABASE`. Append the SSL parameter —
Supabase requires TLS and `psycopg2` honors it from the URL:

```
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
```

Use the **direct** (5432) URL for step 6, the **pooler** (6543) URL for step 7.

## 4. Configure DATABASE_URL

Backend environment only — never in frontend code, never in `NEXT_PUBLIC_*`,
never committed:

- Migration job: `DATABASE_URL=<direct-5432-URL>?sslmode=require`
- App runtime: `DATABASE_URL=<pooler-6543-URL>?sslmode=require`

## 5. Configure backend secrets

All from environment (or a secret store injected as env). Placeholders live in
`backend/.env.example`; real values never touch git:

```
DATABASE_URL=...            # step 4 (never log, never return in API responses)
JWT_SECRET_KEY=...          # ≥32 random chars; rotation = env swap + restart
GROQ_API_KEY=...            # optional at boot; /ai/* returns 503 without it
GROQ_MODEL=openai/gpt-oss-20b
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_TIMEOUT_SECONDS=30
GROQ_MAX_OUTPUT_TOKENS=1024
GROQ_TEMPERATURE=0.0
AI_MAX_EVIDENCE_ITEMS=10
AI_MAX_EVIDENCE_CHARS=2000
AI_MAX_CONVERSATION_MESSAGES=10
AI_MAX_CONVERSATION_CHARS=12000
APP_ENV=prod
LOG_LEVEL=INFO
CORS_ORIGINS=https://<your-frontend-domain>   # explicit; "*" is rejected
DB_POOL_SIZE=5
DB_POOL_MAX_OVERFLOW=10
DOCUMENT_STORAGE_ROOT=./storage/documents
DOCUMENT_MAX_BYTES=26214400
DOCUMENT_MAX_PAGES=200
```

Connection/pool notes:

- `pool_pre_ping` is always on: stale managed connections fail fast.
- Defaults (`5` / `10`) suit a single backend instance on the direct
  connection. Behind the Supabase pooler (6543, PgBouncer transaction mode),
  keep the app pool SMALL (`DB_POOL_SIZE=2..5`, overflow `5..10`) — the pooler
  multiplexes; a large app pool defeats it. `psycopg2` uses no server-side
  prepared statements, so transaction mode is safe for this codebase (plain
  short sessions, no `LISTEN`/`NOTIFY`, no advisory locks).
- Migration job (`alembic/env.py`) uses `NullPool`: one short-lived
  connection, no pooler interaction — always run it against direct (5432).

Never log `DATABASE_URL`, JWTs, API keys, document text, or full conversation
content. Safe log fields: request ID, route, status, latency, model name,
evidence counts, route type. The request-ID middleware behavior is unchanged.

## 6. Run Alembic upgrade head

From `backend/` with the **direct** URL in the environment:

```powershell
alembic current    # expect: empty on a fresh project
alembic heads      # expect: exactly one head (0007)
alembic check      # expect: clean, no model/migration drift
alembic upgrade head
alembic current    # expect: 0007 (the single head)
```

Rules: Alembic is the ONLY schema authority (dashboard SQL edits are not the
source of truth and will be overwritten/diverge). Never run
`Base.metadata.create_all()` (no such call exists in app code). Never run
destructive operations or test cleanup against this database. Never seed fake
financial data, demo users, or test PDFs into production — seed helpers live
in `backend/tests/` and must never execute against the production URL.

## 7. Start backend

Docker (production image, no secrets baked in, non-root, no `--reload`):

```powershell
docker build -t finance-backend ./backend
docker run -d --name finance-api --env-file ./backend/.env -p 8000:8000 finance-backend
```

Or process hosting (Render/Fly/Railway): build command `pip install -r
requirements.txt`, start command
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`, with step-5 env set in
the provider dashboard. Startup performs NO migration and NO schema creation;
it fails fast on missing/invalid settings with a safe message (values never
echoed).

First boot downloads `BAAI/bge-base-en-v1.5` to the Hugging Face cache
(requires outbound network once; thereafter cached). Ingestion and
`/documents/search` return typed errors until the model is present; SQL and
calculation paths are unaffected.

## 8. Configure frontend API origin

Production frontend (Vercel or any Node host):

```
BACKEND_URL=https://<your-backend-origin>
```

The browser only calls same-origin `/api/*`, which the Next.js rewrite proxy
forwards to `BACKEND_URL` — so the browser never needs CORS and never sees
backend secrets. `NEXT_PUBLIC_API_BASE_URL` is a fallback for the same proxy;
`NEXT_PUBLIC_*` must NEVER carry keys, tokens, or database URLs. `localhost`
fallbacks in `next.config.mjs` apply only when the env var is unset (local
dev); production MUST set `BACKEND_URL`.

## 9. Start/deploy frontend

```powershell
cd frontend
npm ci
npm run typecheck; npm run lint; npm run build
```

Deploy the build output (Vercel: `vercel --prod` with `BACKEND_URL` set).
Login → `POST /auth/login` → Bearer token (memory store, `Authorization`
header) → `401/403` surfaces the sign-in prompt and clears the stored token.

## 10. Verify health

- `GET /health` → `{"status":"ok"}` (no DB involved).
- `GET /health/db` → `{"status":"ok","database":"ok","pgvector":"ok"}`
  (HTTP 503 `{"status":"degraded",...}` when DB/pgvector is down — safe JSON,
  never tracebacks or connection strings).

## 11. Verify login

Register or log in via `/auth/register` → `/auth/login` → `GET /auth/me`
returns the user plus company memberships. Wrong/expired tokens → `401`;
wrong-company access → `403 tenant_mismatch`. Authentication architecture is
unchanged from local (custom FastAPI JWT + RBAC; no Supabase Auth).

## 12. Verify finance APIs

Exercise one read and one calculation against known data:

- `GET /revenue`, `GET /expenses`, `GET /transactions` (viewer+).
- `POST /calculations` with a `sum` over a known scope: exact `Decimal`
  string match, `mixed_currency` refused with `422`, empty scope →
  `has_data:false` (`200`, never `500`).

## 13. Verify AI

Controlled test with a small KNOWN dataset only (never real customer data):

1. Upload a 1–2 page test PDF, `POST /documents/{id}/index` → `ready`.
2. `POST /documents/search` → expected chunk in top-k with `page_number`.
3. `POST /calculations` for the authoritative number.
4. `POST /ai/query` → answer carries `citations[]`, `route`, evidence refs;
   numbers match the calculation exactly (LLM explains only).
5. `GET /conversations` shows the persisted thread.
6. Repeat as a second company's user → zero cross-tenant hits/citations.

## 14. Verify tenant isolation

Run the real two-tenant matrix against this database (production-like PG):

```powershell
cd backend
pytest tests/test_tenant_isolation.py tests/test_finance_tenancy.py `
  tests/test_finance_authz.py tests/test_conversation_tenancy.py -q
```

Company A tokens must never read B's finance rows, documents, chunks,
vectors, or conversations (`403/404` + audit-shaped errors, B-data never in
payloads). The full gate before cutover:

```powershell
pytest            # entire backend suite
ruff check .
ruff format --check .
alembic check
```

plus frontend `typecheck` + `lint` + `build` (step 9) and a repo secret scan:
no `gsk_`, no committed `.env`, no service-role keys, no `allow_origins=["*"]`
(see "Security checklist" below).

---

## Storage status (documented limitation, not a silent gap)

Document bytes live behind the `StorageService` abstraction
(`app/services/storage.py`); production runs the same `LocalFileStorage`
under `DOCUMENT_STORAGE_ROOT`. Consequences:

- Single-instance backend: uploads work. Multi-instance / ephemeral-disk
  hosting LOSES files on redeploy — PDFs must then move to durable object
  storage via a new `StorageService` implementation (private bucket, backend-
  minted access only). That adapter is explicitly future work, not this phase.
- Never store PDF blobs in PostgreSQL (no binary columns exist — enforced by
  `test_no_binary_columns_in_postgres_schema`). Never expose storage
  credentials to the frontend.

## CORS status

No `allow_origins=["*"]` exists anywhere. Local dev uses the same-origin
proxy (no CORS middleware loaded when `CORS_ORIGINS` is empty). Production
sets `CORS_ORIGINS` to explicit frontend origin(s); `*` fails startup fast.
Direct browser → backend calls outside the allowlist get no ACAO headers.

## Security checklist

- [ ] No `.env` tracked by git (`.gitignore` covers `.env`, `.env.*` except
      `.env.example`); `.env.example` holds placeholders only.
- [ ] No `gsk_` / API keys / DB passwords / JWT secrets in the repo or logs.
- [ ] `DATABASE_URL` backend-only; no `NEXT_PUBLIC_*` secret.
- [ ] `CORS_ORIGINS` explicit in prod; no wildcard-with-credentials.
- [ ] Health endpoints leak no secrets/traces.
- [ ] Tenant-isolation suites green against the target database.
- [ ] Upload hardening unchanged (PDF magic bytes, 25 MB / 200-page caps,
      per-company SHA-256 dedupe, analyst+ only).

## Deployment limitations (explicit)

- No live Supabase verification has run from THIS workspace (no project
  credentials here): readiness is implemented and locally proven; steps
  1–6 + 10–14 must still execute once against the real project. The app must
  NOT be declared production-live until the gates in step 14 are green on the
  Supabase database.
- Single-instance file storage (see "Storage status").
- Auth is unchanged custom JWT (no Supabase Auth, no RLS-as-authorization —
  repository-level `company_id` filtering remains the enforcer; RLS may be
  added later only as defense-in-depth with an approved amendment).
- Out of scope (locked): new AI providers, new embedding models, semantic
  conversation memory, voice/OCR/vision, agents, streaming, billing, mobile.
