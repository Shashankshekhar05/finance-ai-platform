# Finance Dashboard — Backend (Phase 1: Foundation)

Foundation only: FastAPI + Pydantic Settings + SQLAlchemy 2.x engine/session
infrastructure + Alembic with the pgvector extension. No domain tables, no
auth, no RAG, no frontend — those arrive in later phases.

Same code runs against local PostgreSQL now and Supabase PostgreSQL later:
only the `DATABASE_URL` value changes (see ARCHITECTURE.md §10A).

## 1. Create the Python environment

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Requires Python 3.11+.

## 2. Install dependencies

```powershell
pip install -r requirements.txt
```

## 3. Configure `.env`

```powershell
copy .env.example .env
```

Then edit `.env` — local development value:

```
DATABASE_URL=postgresql+psycopg2://finance:finance@localhost:5432/finance
APP_ENV=local
LOG_LEVEL=INFO
```

`.env` is gitignored. Never commit real credentials. Only variable names
belong in `.env.example`.

## 4. Run PostgreSQL (with pgvector)

Option A — Docker (recommended, no local install needed):

```powershell
docker run -d --name finance-postgres `
  -e POSTGRES_USER=finance -e POSTGRES_PASSWORD=finance `
  -e POSTGRES_DB=finance -p 5432:5432 pgvector/pgvector:pg16
```

Option B — native PostgreSQL 16+ with the `pgvector` extension installed,
with a `finance` user/database matching `DATABASE_URL`.

Supabase later: point `DATABASE_URL` at the Supabase pooler URL. No code
or migration changes required (Alembic remains the migration authority).

## 5. Run Alembic

From `backend/` with the venv active:

```powershell
alembic upgrade head        # installs the `vector` extension (no tables yet)
alembic history             # list migrations
alembic check               # verify no model/migration drift
```

Application startup never creates schema (`create_all` is forbidden).

## 6. Start FastAPI

```powershell
uvicorn app.main:app --reload --port 8000
```

Endpoints:

- `GET /health` → `{"status": "ok"}`
- `GET /health/db` → `{"status": "ok", "database": "ok", "pgvector": "ok"}`
  (HTTP 503 `{"status": "degraded", ...}` when the database is down —
  structured JSON, never tracebacks or connection strings.)

## 7. Run tests

```powershell
pytest            # full suite (live-DB tests skip if Postgres is down)
pytest -m "not integration"
ruff check .
```

What is covered: `/health`, `/health/db` (both DB states), session
lifecycle (commit/rollback/close incl. live-Postgres paths), settings
validation. See TESTING_RULES.md.

## 8. Auth (Phase 2: identity + tenants)

Migrations `0002`/`0003` add `users`, `companies`, `user_roles`
(viewer/analyst/admin, one role per user per company). Required env:

```
JWT_SECRET_KEY=<random string, at least 32 characters>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

Endpoints:

- `POST /auth/register` → `201` safe user + personal company (viewer role)
- `POST /auth/login` → `200` `{"access_token", "token_type": "bearer"}`
- `GET /auth/me` (Bearer token) → `200` safe user + memberships

Failures use the shared `{error:{code,message,details,request_id}}`
envelope (`invalid_credentials`, `email_already_registered`,
`authentication_required`, `invalid_token`, `token_expired`,
`inactive_user`, `insufficient_permissions`, `tenant_mismatch`).
Passwords are bcrypt-hashed; `password_hash` never leaves the backend.

## 9. Finance (Phase 3: money domain)

Migration `0004` adds `revenue`, `expenses`, `transactions`,
`financial_metrics` — all company-scoped, `NUMERIC` amounts (never float),
amounts serialized as exact strings in JSON.

Endpoints (all Bearer-authenticated, tenant taken from the token):

- `GET /revenue`, `POST /revenue`, `GET/PATCH /revenue/{id}`, `DELETE /revenue/{id}`
- Same shape for `/expenses` and `/transactions`
- `GET /financial-metrics`, `GET /financial-metrics/{id}` (read-only;
  metrics are recorded by the service layer / future calculation engine)

Roles: viewer reads; analyst creates/updates; admin deletes.
Lists paginate (`limit` 1–200 default 50, `offset`) with allowlisted
`sort` + `order`, and per-resource filters (date ranges, category,
department, region, segment, type, account, fiscal year/quarter).
PATCH `fiscal_quarter` requires `fiscal_year` in the same payload;
fiscal fields are explicit only (no company calendar yet, nothing derived).

## 10. Documents (Phase 4: ingestion foundation)

Migration `0005` adds `documents` + `document_pages` (no chunks/embeddings
yet — those arrive with the RAG phases). `PyMuPDF` is the only PDF
dependency (text, raster images, and table detection all come from it).

Required env (`backend/.env`, gitignored):

```
DOCUMENT_STORAGE_ROOT=./storage/documents
DOCUMENT_MAX_BYTES=26214400
DOCUMENT_MAX_PAGES=200
```

Endpoints (all Bearer-authenticated, tenant taken from the token):

- `POST /documents/upload` (analyst+) — multipart `file` + `title` +
  optional `fiscal_year`. `201` first ingest, `200 {"duplicate": true}`
  when the bytes already exist for the company. PDF-only (magic bytes
  verified, not just extension/MIME), 25 MB / 200-page caps.
- `GET /documents` (viewer+) — paged, optional `?status=` filter.
- `GET /documents/{id}` (viewer+) — metadata (no storage key, no bytes).
- `GET /documents/{id}/pages` (viewer+) — 1-based pages in order with
  `page_type` (`narrative|table|visual|mixed`), flags, and normalized text.
- `POST /documents/{id}/reprocess` (analyst+) — retry a `failed` document;
  `409` otherwise.

Files land under `{storage_root}/{company_id}/{document_id}.pdf`
(original filenames are metadata only). Statuses:
`uploaded → processing → indexed`, or `→ failed` with a typed code
(retryable). Same bytes re-uploaded never create a second row per company.

## 11. Retrieval (Phase 5: chunking + BGE + pgvector)

Migration `0006` adds `document_chunks` (`embedding vector(768)`, HNSW
cosine index) plus `documents.embedding_status` (`pending|indexing|ready|
failed` — separate from pages-`indexed`; only `ready` is retrievable).

- **Embedding model**: `BAAI/bge-base-en-v1.5` via SentenceTransformers
  (downloads once to the Hugging Face cache on first use; needs network).
  768 dims, L2-normalized both sides. Query prefix
  `Represent this sentence for searching relevant passages: `, documents
  unprefixed. Model loads once per process; chunk texts embed in batches.
- **Chunking**: single-page, deterministic (page → paragraph → sentence →
  hard word-boundary split). `RAG_CHUNK_SIZE=2000` chars (~500 tokens),
  `RAG_CHUNK_OVERLAP=256` (~64 tokens). `<50`-char and visual-only pages
  skipped; table pages kept whole with `chunk_type=table`.
- **pgvector**: tenant-first SQL (`WHERE company_id` inside the query),
  cosine distance (`<=>`), score reported as `1 - distance`, deterministic
  distance-then-id ordering. No embeddings ever leave the API.
- **Endpoints** (Bearer-authenticated, tenant from token):
  - `POST /documents/{id}/index` (analyst+) — delete/rebuild chunks,
    idempotent; returns status + counts.
  - `POST /documents/search` (viewer+) — `{query (≤1000 chars),
    top_k (default 8, max 20), document_id?, fiscal_year?, page_number?}`
    → `{results: [{chunk_id, document_id, document_title, page_number,
    chunk_index, chunk_type, text, score}]}`. No LLM, evidence only.
- **Config** (`backend/.env`): `EMBEDDING_MODEL_NAME`,
  `EMBEDDING_DIMENSIONS=768`, `EMBEDDING_BATCH_SIZE=32`,
  `RAG_CHUNK_SIZE=2000`, `RAG_CHUNK_OVERLAP=256`, `RAG_TOP_K=8`,
  `RAG_MAX_TOP_K=20`, `RAG_SIMILARITY_THRESHOLD=0.0` (baseline, uncalibrated).
- **Evaluation**: `pytest tests/test_retrieval_eval.py -s` prints
  recall@K/precision@K/MRR on the 3-question smoke set (not a benchmark).
  Current smoke result: recall@3 = 1.00, MRR@3 = 1.00.

## 12. Calculations (Phase 6: deterministic engine, no LLM)

No migration (read-only over Phase 3 tables). The LLM is never the
calculator: this service is the authority; a future LLM may only explain
its results + provenance, never override them.

- **Endpoint**: `POST /calculations` (viewer and above — read-only).
  No `company_id` in the body; tenant scope comes only from the token.
- **Datasets** (closed enum → fixed columns, never client table names):
  `revenue | expense | transaction`.
- **Operations**: `sum | count | average | minimum | maximum`
  (+ `group_by` on allowlisted dims for `sum`/`count`),
  `growth_rate | variance` (explicit `current_period` + optional
  `comparison_period`; omitted comparison = previous fiscal year, same
  quarter shape), `margin` (`revenue` vs `expense`: absolute + percent).
- **Filtering**: per-dataset allowlists (fiscal year/quarter, inclusive
  date range, category/segment/region/department/vendor/type/account,
  currency). Wrong-dataset fields → `422 invalid_filter`; quarter without
  year, reversed dates → `422`; over-max `top` N/A. Fiscal scope comes from
  stored values only — never derived from calendar dates.
- **Decimal semantics**: PostgreSQL aggregates, Python `Decimal` math, no
  float anywhere. Money quantized to 2dp at the output boundary only
  (`ROUND_HALF_UP`); percentages likewise (`unit: "percent"`, `"12.45"`
  means 12.45%). Money serializes as exact strings.
- **No-data vs zero**: empty scope → `has_data: false`, `value: null`,
  `status: "no_data"` (except `count`, where `0` is truthful). Zero
  denominators → `status: "undefined"` + reason (never Infinity/NaN).
  Positive-amount `CHECK`s make API-level zero denominators unreachable
  today; the branch stays as defense.
- **Currency**: single-currency-per-company assumed, no conversion. Mixed
  currencies in scope → `422 mixed_currency`, never silent addition.
- **Provenance** on every result: dataset, operation, filters, group_by,
  company scope, record counts, timestamp, `source_type:
  structured_finance`.
- **Evaluation**: `pytest tests/test_calculation_eval.py -s` checks the
  §40 values exactly (revenue 1200.00, growth 20.00%, expense 300.00,
  profit 900.00, margin 75.00, regions 1200.00/400.00). Not a benchmark —
  a correctness gate.

## 13. AI Answers (Phase 7: Groq evidence grounding, no router yet)

The LLM explains supplied evidence only. Numbers come from the Phase 6
engine, narrative from tenant-scoped retrieval — never from the model.

- **Groq setup** (`backend/.env`, gitignored): `GROQ_API_KEY=<key>`
  (optional — the app boots and serves everything else without it;
  `/ai/answer` then fails closed with `503 llm_unavailable`),
  `GROQ_MODEL=llama-3.3-70b-versatile`, `GROQ_BASE_URL`,
  `GROQ_TIMEOUT_SECONDS=30`, `GROQ_MAX_OUTPUT_TOKENS=1024`,
  `GROQ_TEMPERATURE=0.0`, `AI_MAX_EVIDENCE_ITEMS=10`,
  `AI_MAX_EVIDENCE_CHARS=2000`. No new pip packages (plain httpx client).
- **Endpoint**: `POST /ai/answer` (viewer+, Bearer auth). Body: `question`
  (1–2000 chars) plus at least one backend-resolved evidence spec —
  `calculation` (a `CalculationRequest`) and/or `retrieval` (a search
  spec). Raw client evidence is never accepted; the backend builds the
  packet from tenant-scoped services. No tools, no SQL, no routing.
- **Grounding**: backend-assigned IDs (`[CALC-n]`, `[DOC-n]`); system prompt
  and `<UNTRUSTED_EVIDENCE>` block strictly separated; calculation items
  bannered AUTHORITATIVE (1200 beats a conflicting 1400 — the model may
  note the discrepancy, never resolve it by guessing).
- **Citations**: machine format `[DOC-n]`/`[CALC-n]`; every cited ID is
  validated in code. Unknown IDs are stripped and the answer is flagged
  `citation_invalid` (deterministic; zero retries). Response statuses:
  `grounded | insufficient_evidence | citation_invalid`.
- **No-evidence behavior**: empty packet → `insufficient_evidence` with NO
  provider call (no tokens spent).
- **Provider errors**: timeout/network/5xx/rate-limit → `503
  llm_unavailable`; bad credentials/unknown model/bad request/malformed
  response → `502 llm_error`. No retries, no provider switching, no raw
  provider internals in responses. Logs carry model/latency/counts only —
  never keys, tokens, prompts, or evidence.

## 14. AI Query Router (Phase 8: deterministic orchestration, still no LLM routing)

`POST /ai/query` (viewer+) turns a question into a typed `RoutePlan` with a
pure deterministic router (no LLM, no DB, no randomness — same input always
yields the same plan), executes it through existing tenant-scoped services,
and answers via the Phase 7 pipeline. `POST /ai/answer` is unchanged.

- **Routes**: `calculation | sql | rag | hybrid`, plus conservative
  `clarify` (explicit guidance instead of a guess).
- **Precedence**: explicit `mode` → hybrid (explanation + numeric signal)
  → calculation → sql → rag → clarify. Document-framed questions stay
  narrative unless they name a dataset AND a fiscal year; bare fact
  lookups ("What was revenue in FY2025?") take the SQL list path.
- **Specs**: the router derives executable `CalculationRequest` /
  `SearchRequest` / `StructuredQuerySpec` from text (years, quarters,
  datasets, `by <dim>`); caller-provided specs for the chosen route are
  honored verbatim. Underivable parameters → clarify, never invented.
  No `company_id`, no SQL, no raw expressions anywhere.
- **Execution**: one calculation and/or one retrieval plus at most one LLM
  call; SQL rows become `[DATA-n]` evidence; empty evidence →
  `insufficient_evidence` with no provider call. Calculation stays
  authoritative; conflicts are preserved, never reconciled by guessing.

## 15. Conversations (Phase 9: persistent threads, history as context only)

`conversations` (one owner + one company; admins manage company-wide) and
append-only `conversation_messages` (`user | assistant`, per-thread
`sequence`, no system/token/secret content by CHECK + review). Migration
`0007`. Env: `AI_MAX_CONVERSATION_MESSAGES=10`,
`AI_MAX_CONVERSATION_CHARS=12000` (`.env`, gitignored; see `.env.example`).

- **Endpoints** (Bearer auth, tenant from token, uniform 404 for foreign
  IDs): `POST /conversations` (viewer+, optional ≤200-char title),
  `GET /conversations` (paged; own threads, or company-wide for admins),
  `GET /conversations/{id}` (bounded recent messages), `DELETE
  /conversations/{id}` (own thread or admin; cascades messages only).
- **`POST /ai/query` gains optional `conversation_id`**: access re-validated
  per request; the user question persists, then routing executes with the
  previous user turn as a dataset-only hint, then the answer renders with
  bounded history as supporting context, then the assistant reply persists.
  Omitted id = legacy stateless path (zero rows touched). Provider failure
  leaves the user message persisted and writes no assistant message.
- **Authority**: history renders in a delimited `<CONVERSATION_CONTEXT>`
  block and NEVER feeds evidence, citations, or numbers — a stale `$5M`
  in history loses to a fresh `$4.2M` calculation every time (tested).
  History is untrusted input like document text (system rule 9).
- **Ordering**: explicit per-thread `sequence` (UNIQUE) assigned under a
  parent-row `FOR UPDATE` lock; best-effort serialization, constraint
  backstop, no distributed-lock claims.
