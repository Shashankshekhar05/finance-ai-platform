# ARCHITECTURE.md — System Architecture

> Status: NORMATIVE (subordinate to `AGENTS.md`, authoritative over implementation layout).
> Audience: implementer agents + human reviewers.
> This doc defines WHAT the system is, its components, responsibilities, boundaries, dependencies, and data flows. It does NOT contain code.

## 1. Goal & Non-Goals

### 1.1 Goal
A production-quality, demo-safe AI Finance Dashboard:

- Structured financial analytics (revenue / expenses / transactions / metrics) via SQL.
- Unstructured understanding (annual reports, filings, PDFs with text, tables, visuals) via RAG.
- Deterministic financial math (growth, margins, ratios) in Python — never LLM arithmetic.
- Hybrid reasoning that joins numbers with narrative and cites both.
- Multi-tenant isolation by `company_id`.
- Public demo readiness: explainable answers, page-aware citations, graceful `insufficient_evidence` handling.

### 1.2 Non-Goals (v1)
- Real-time market data streaming / trading execution.
- Multi-database federation (only PostgreSQL + pgvector).
- Custom embedding-model training; custom LLM training/fine-tuning.
- Fully offline LLM inference (Groq is remote; embeddings are local via SentenceTransformers).
- Automated accounting / audit certification.

## 2. Locked Stack (Recap — See AGENTS.md §3)

| Layer | Choice |
|-------|--------|
| Backend | Python + FastAPI |
| ORM / validation | SQLAlchemy 2.x + Pydantic v2 |
| Migrations | Alembic only |
| DB + vectors | PostgreSQL + pgvector, embedding `vector(768)` |
| Embeddings | `BAAI/bge-base-en-v1.5` via SentenceTransformers (local) |
| LLM | Groq (backend-only, never browser) |
| Frontend | Next.js + TypeScript + Tailwind CSS |
| Auth | Backend JWT + RBAC (`viewer`, `analyst`, `admin`) |

Dependency direction: `Frontend → Backend API → Services → Repositories → PostgreSQL`. AI services (router, executors, RAG, calculations, Groq client, embedding service) live in backend only.

## 3. High-Level System Diagram (Logical)

```
                    ┌────────────────────────────┐
                    │  Next.js + TS + Tailwind   │
                    │  UI / interaction / charts │
                    │  loading + error states   │
                    └─────────────┬──────────────┘
                                  │ HTTPS / JSON (JWT)
                                  ▼
                    ┌────────────────────────────┐
                    │   FastAPI Backend          │
                    │  ┌──────────────────────┐  │
                    │  │ API layer (thin)     │  │
                    │  │ auth, validation,   │  │
                    │  │ tenant scoping       │  │
                    │  └─────────┬────────────┘  │
                    │  ┌─────────▼────────────┐  │
                    │  │ Services (logic)     │  │
                    │  │ router / executors / │  │
                    │  │ calc / RAG / ingest  │  │
                    │  └─────────┬────────────┘  │
                    │  ┌─────────▼────────────┐  │
                    │  │ Repositories (DB)    │  │
                    │  │ SQLAlchemy 2.x       │  │
                    │  └─────────┬────────────┘  │
                    └────────────┼───────────────┘
                                 ▼
                    ┌────────────────────────────┐
                    │  PostgreSQL + pgvector     │
                    │  structured + vector(768)  │
                    │  Alembic migrations        │
                    └────────────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
     SentenceTransformers   Groq LLM API        PDF/Table/Vision
     bge-base-en-v1.5       (explain only)      parsers (ingest)
     (embed only)           (never calculate)
```

External calls: only backend → Groq. Embeddings run in backend process/worker (local model). Frontend never calls Groq, never touches DB, never embeds.

## 4. Component Responsibilities & Boundaries

### 4.1 Frontend (Next.js + TS + Tailwind)
**Responsible for:**
- Pages: dashboards, document list/detail, AI chat, admin (roles/company), login.
- Data fetching via backend REST API with JWT; chart/visualization rendering.
- Loading states, empty states, error states (typed API errors), pagination.
- Display of citations (`document title` + `page_number` + snippet) and `insufficient_evidence` messaging.
- Display-only role gating (hide/show UI) — NEVER authoritative.

**Must NOT:**
- Contain DB logic, SQL, pgvector queries, embeddings, Groq calls, API keys.
- Perform authoritative financial math or authorization decisions.
- Bypass backend validation.

Contracts: consumes versioned backend DTOs (Pydantic → OpenAPI → TS types). All money shown as formatted strings + currency; raw `Decimal` serialized as string.

### 4.2 Backend API Layer (FastAPI routers)
Thin by rule (see `DEVELOPMENT_RULES.md`):
- Parse/validate input (Pydantic v2), authenticate JWT, authorize RBAC, resolve tenant `company_id`.
- Delegate to exactly one service method; map service result / domain error to HTTP + error envelope.
- No SQL, no embedding, no Groq, no math here.

Planned route groups (conceptual, not exhaustive):
- `/api/auth/*` — login, refresh, me.
- `/api/companies/*`, `/api/users/*`, `/api/roles/*` — admin.
- `/api/documents/*` — upload, list, get, pages, ingest status.
- `/api/finance/*` — revenue, expenses, transactions, metrics queries.
- `/api/ai/ask` — single Q&A entrypoint (router + executors).
- `/api/ai/conversations/*` — history.
- `/api/health` — liveness/readiness (no secrets).

### 4.3 Service Layer (Business Logic)
Owns all decisions and orchestration:

| Service | Responsibility |
|---------|----------------|
| `AuthService` | Credential verify, JWT mint/refresh, role resolution. |
| `TenantService` / scope helper | Resolve `company_id` from JWT; enforce on every call. |
| `DocumentService` + `IngestionService` | Upload validation, PDF→pages, content classification, text/table/visual extraction, chunking, embedding dispatch, persist + status tracking. |
| `QueryRouter` | Classify question → `RouteDecision{route, confidence, rationale, slots}`. No execution. See §7. |
| `SqlExecutor` | Parameterized SQL over tenant-scoped structured tables; returns rows + query metadata. |
| `RagExecutor` | Embed query → pgvector search (tenant-filtered) → optional rerank → evidence set. |
| `CalculationExecutor` | Deterministic `Decimal` math (growth, margins, aggregates) over verified inputs. |
| `HybridOrchestrator` | Compose SQL + RAG + Calculation results; assemble evidence bundle for LLM. |
| `EvidenceAssembler` | Build bounded LLM context: rows + chunks + calc results + citations. Enforces token budget + redaction. |
| `LLMService` (Groq) | Explain-only generation with system prompt that forbids invention; must echo citations and `insufficient_evidence` when flagged. |
| `AuditService` | Append-only audit logs for auth, ingest, AI Q&A, admin actions. |

### 4.4 Repository / Persistence Layer
- Sole owner of SQLAlchemy 2.x sessions, queries, pgvector operators (`<->`, `<#>`, `<=>`).
- Every method takes `company_id` (except explicit global admin-audit paths) and applies it as a WHERE filter — including vector search.
- No business rules, no LLM, no math beyond query aggregation; returns ORM/domain objects to services.
- Migrations via Alembic only. No `create_all()` in app code.

### 4.5 Data / AI Infrastructure
- **PostgreSQL + pgvector**: single source of truth for structured + vectors (see `DATABASE_RULES.md`).
- **Embedding service**: loads `bge-base-en-v1.5` once, normalizes embeddings, outputs 768-d vectors. Batch ingest; single-query path cached per request.
- **Groq client**: backend-only wrapper with timeout, retry (bounded), secret from env, structured logging without prompt/secret leakage.
- **Ingestion workers**: sync in-request for small PDFs (demo) + background worker path (Celery/ARQ or FastAPI BackgroundTasks — decision deferred to implementation, must not violate layering).

## 5. Data Flows

### 5.1 Document Ingestion
```
Upload (analyst+) → validate (type/size) → store blob ref → create document(row, status=pending)
 → split PDF → document_pages rows (page_number, raw refs)
 → classify each page region: TEXT | TABLE | VISUAL
 → TEXT: extract (pypdf/pdfplumber) → clean
 → TABLE: extract (camelot/tabula/pdfplumber) → serialize to markdown/CSV + preserve bbox
 → VISUAL: caption/OCR (vision-capable parser; VLM description stored as text surrogate + image ref)
 → chunk (page-aware, overlap, table-aware: never split a table row group blindly)
 → embed (bge-base-en-v1.5, 768-d, normalized)
 → persist document_chunks {company_id, document_id, page_number, content_type, text, embedding vector(768), token_count}
 → update document status=ready/failed + audit log
```
All chunk rows carry `company_id` denormalized for tenant-filtered vector search. Failures are per-document with typed error + retry affordance.

### 5.2 AI Q&A (Router → Executors → LLM)
```
POST /api/ai/ask {question, company_id?, conversation_id?}
 → authN + authZ + tenant resolve
 → QueryRouter → RouteDecision{route, confidence, rationale, slots}
 → branch:
    SQL         → SqlExecutor → rows
    RAG         → RagExecutor → chunks+citations
    CALCULATION → SqlExecutor(fetch inputs) → CalculationExecutor → verified numbers
    HYBRID      → SqlExecutor + RagExecutor + CalculationExecutor → merged evidence
 → EvidenceAssembler (budget, cite, insufficient_evidence check)
 → IF insufficient → return insufficient_evidence (no LLM call needed, or LLM called only to phrase it with no facts)
 → ELSE LLMService.explain(evidence) → answer + citations
 → persist ai_messages (question, route, evidence refs, answer) + audit log
 → return {answer, citations[{document_id, page_number, chunk_id}], route, confidence, warnings}
```
Routing and execution are in separate modules; executors never re-route.

### 5.3 Structured Analytics (Dashboards)
```
GET /api/finance/*?company_id=…&from=&to=
 → authN/Z + tenant check → service validates range → repository aggregates → DTOs → frontend charts
```
No LLM in this path. Math (totals, series) in service/repository with `Decimal`.

## 6. Tenancy & Auth Enforcement (Summary — Details in SECURITY_RULES.md)

- JWT (backend-minted) carries `sub (user_id)`, `company_id`, `roles[]`, `exp`.
- Request pipeline: `authenticate → authorize(role) → scope(company_id)` before any service logic.
- Every structured query AND every pgvector query includes `company_id = :cid`.
- Cross-company access allowed only for explicit `admin` audit endpoints, each emitting an `audit_logs` row.
- Frontend tenant switcher is UX only; backend re-validates membership.

## 7. Query Routing Design (Conceptual)

`QueryRouter` input: `{question, conversation history (bounded), company context}`.
Output: `RouteDecision{ route: SQL|RAG|CALCULATION|HYBRID, confidence: 0..1, rationale: string, slots: {period?, metric?, company_id, needs_narrative: bool} }`.

| Route | Trigger (intent) | Example | Executor chain |
|-------|------------------|---------|----------------|
| SQL | Fact lookup over structured tables | "What was revenue in 2025?" | `SqlExecutor` |
| RAG | Narrative/qualitative in documents | "What did management say about future growth?" | `RagExecutor` |
| CALCULATION | Derived math over known figures | "What was YoY revenue growth?" | `SqlExecutor` → `CalculationExecutor` |
| HYBRID | Number + explanation ("why") | "Revenue increased significantly. Why?" | `Sql + Rag + Calc` via `HybridOrchestrator` |

Rules:
- Router is deterministic-first (rules/heuristics + optional LLM classifier with constrained output schema). It never fetches evidence itself.
- Low confidence (< threshold, e.g., 0.55 — tunable) → default `HYBRID` with `low_confidence` flag, or ask clarifying question. Never guess silently.
- Every decision is logged + persisted with the message for audit and routing-accuracy tests (see `TESTING_RULES.md`).

### 7A. Phase 8 Implementation Note (Deterministic Subset)

The shipped router (`app/services/router.py` + `POST /ai/query`) implements
this design without the LLM-classifier and confidence options: pure
rules over the question text (no DB, no randomness), typed `RoutePlan`
instead of scored `RouteDecision`, and conservative `clarify` instead of a
low-confidence default. Route mapping: SQL → existing list services (fact
lookup, `[DATA-n]` evidence); CALCULATION → calculation engine;
RAG → pgvector retrieval; HYBRID → one calculation + one retrieval
(the SQL leg of hybrid composition remains future work). No migration,
no new provider, no tools.

## 8. Financial Correctness by Construction

- `CalculationExecutor` is the ONLY authority for numbers: uses `Decimal`, explicit rounding policy, null/zero-division handling (returns `undefined` + reason, not `0` or `inf`).
- LLM system prompt (defined in `RAG_RULES.md`) forbids arithmetic and invention; LLM receives pre-computed numbers + citations and only verbalizes them.
- Missing inputs → `insufficient_evidence` with `missing: [...]` (e.g., `["revenue.2024"]`), never interpolation.
- All calc functions require deterministic unit tests with frozen fixtures.

## 9. Observability, Errors, Audit

- Structured JSON logs (request_id, user_id, company_id, route, latency, error.code). No secrets, no full prompts at info level.
- Error envelope: `{ error: { code, message (safe), details?, request_id } }`. HTTP mapping defined in `DEVELOPMENT_RULES.md`.
- Audit: `audit_logs` rows for login, role change, document upload/ingest, AI Q&A (route + citation ids, not full PII), finance exports.
- Health: `/api/health` (DB + pgvector + embedding-model-loaded + Groq-reachable flags, without secrets).

## 10. Deployment View (Target, Not Implementation)

- Backend: single FastAPI service + Postgres (managed) with `pgvector` extension; embedding model bundled or sidecar-cached; Groq via HTTPS.
- Frontend: Next.js (SSR/SSG for marketing + CSR for dashboard) calling backend base URL from server-side env or public non-secret config.
- Env-driven config; `.env` never committed; `.env.example` at implementation time.
- Migration job runs `alembic upgrade head` separately from app startup.

## 10A. Future Supabase Migration / Deployment Strategy (Optional Path, Not Default)

> Status: PERMITTED DEPLOYMENT OPTION, not a stack change. Supabase Postgres IS PostgreSQL + pgvector under managed hosting. Adopting it MUST NOT change the locked decisions in `AGENTS.md` §3–§4 (FastAPI, SQLAlchemy 2.x, Alembic, BGE 768, Groq, Next.js, backend-owned auth logic). If any deviation below becomes necessary, STOP per `AGENTS.md` §2 + §4 and wait for approval.

1. **What Supabase may provide:** managed PostgreSQL with the `vector` extension, connection pooling (PgBouncer transaction mode), object storage for original PDFs/images, and optional hosted auth — USED ONLY as infrastructure, never as a replacement for backend business logic.
2. **What Supabase MUST NOT replace:**
   - Alembic remains the ONLY schema migration authority. Supabase SQL editor / dashboard migrations are forbidden as the source of truth. Every Supabase schema state MUST be reproducible by `alembic upgrade head` from this repo.
   - SQLAlchemy 2.x remains the ONLY ORM. Direct PostgREST/Supabase-JS database access from the frontend is FORBIDDEN — all frontend traffic still goes through the FastAPI backend (tenant scoping + RBAC preserved).
   - pgvector semantics unchanged: `vector(768)`, same index strategy (see `DATABASE_RULES.md` §5), same tenant-filtered queries. Verify the Supabase project's pgvector version supports the chosen index (`hnsw` vs `ivfflat`) before cutover.
   - Auth: backend JWT + `user_roles` RBAC remain authoritative. Supabase Auth/RLS may ONLY be adopted later as defense-in-depth with an explicit approved amendment — never silently, never as the sole enforcer in v1.
   - Embeddings/LLM unchanged: BGE-base-en-v1.5 local, Groq backend-only. No Supabase Edge Function may call Groq with a duplicated secret.
3. **Migration path (if approved):**
   - Step 1: provision Supabase project (pinned Postgres + pgvector versions), enable `vector` extension via a tracked Alembic migration, not dashboard clicks.
   - Step 2: run `alembic upgrade head` against the Supabase connection string in staging; run full DB + RAG + tenancy test suites green.
   - Step 3: data migration (pg_dump/pg_restore or logical replication for structured tables; re-embed OR copy `vector(768)` columns with recorded model revision — never mix revisions).
   - Step 4: point backend `DATABASE_URL` (pooler URL, transaction-mode caveats documented: no long-lived prepared statements across pooled connections) + storage refs at Supabase; keep Groq/JWT secrets in existing env management.
   - Step 5: cutover with rollback plan (keep prior managed Postgres read-ready until verification window passes); update deployment docs only, no code-architecture change.
4. **Storage mapping (if used):** original PDFs/images → Supabase Storage (private buckets, signed URLs minted by BACKEND only); parsed text/chunks/vectors stay in Postgres per current schema. Public buckets forbidden for financial documents.
5. **Decision gate:** Supabase adoption requires: (a) pgvector version check, (b) Pooler compatibility test with SQLAlchemy, (c) Alembic-from-scratch prove-out, (d) tenant-isolation suite passing against Supabase. Until then, the default in §10 stands.

## 11. Key Architectural Decisions (ADRs, Abridged)

| # | Decision | Rationale | Consequence |
|---|----------|-----------|-------------|
| A1 | Single Postgres for OLTP + vectors | Fewer moving parts, tenant filter in one place, demo-deployable | Must tune pgvector indexes (HNSW/IVFFlat) later; no vector-DB swap without approval |
| A2 | BGE-base 768 local embeddings | Good quality/cost, no embedding API key, deterministic versioning | Model load cost at startup; must pin revision |
| A3 | Groq backend-only | Fast inference, key stays secret | Remote dependency; need timeout/fallback messaging |
| A4 | Router/executor split | Testability (routing accuracy vs execution correctness), auditability | More modules; strict interface discipline |
| A5 | Alembic only | Auditable schema evolution for finance data | No startup `create_all`; CI must run migrations |
| A6 | Decimal math service | Avoid float drift in money; LLM can't do math reliably | Serialization care (string) + explicit rounding policy |

## 12. What This Doc Deliberately Omits

- File-by-file code layout, function signatures, SQL text, prompt text — these belong in implementation + `RAG_RULES.md` / `DATABASE_RULES.md` / `DEVELOPMENT_RULES.md`.
- Environment values, model hyperparameters, index tuning numbers — decided at implementation with justification.
