# DEVELOPMENT_RULES.md — Implementation Discipline

> Status: NORMATIVE (subordinate to `AGENTS.md`, `ARCHITECTURE.md`, `SECURITY_RULES.md`).
> Scope: how backend + frontend code MUST be structured, styled, and handled. No code in this file — only rules.

## 1. Guiding Principles

1. Simple > clever. Prefer boring, readable solutions.
2. No premature optimization. No speculative abstraction.
3. No duplicated logic — one canonical module per concern (money math, auth, tenant scoping, citations).
4. No unnecessary dependencies. Each new dep needs: purpose, alternative, size/security note. Locked-stack deps (§3 of AGENTS.md) need human approval to change.
5. Small focused modules: soft limit ~400 lines/file, ~50 lines/function. Exceed only with a comment justifying why a split would hurt cohesion.
6. Typed everything: Pydantic v2 (backend), TypeScript strict (frontend), SQLAlchemy 2.x `Mapped[...]` typing.
7. Thin routes, fat-enough services, isolated persistence (see §2).

## 2. Layering (Mandatory)

```
backend/
  api/          # FastAPI routers: validate → authZ → call ONE service → map to HTTP. No SQL, no LLM, no math.
  services/     # Business logic: router, executors, calculations, RAG assembly, ingest, auth, audit.
  repositories/ # SQLAlchemy queries + pgvector search. Take company_id, return domain objects. No business rules.
  schemas/      # Pydantic v2 request/response DTOs. Single source for OpenAPI.
  models/       # SQLAlchemy ORM models. No business logic.
  core/         # Config, security (JWT), errors, logging, middleware.
  workers/      # Optional background ingestion jobs. Must call services, not duplicate them.
frontend/
  app/ (routes) # Next.js routes + layouts. Server/client split explicit.
  components/   # Presentational + container components. No direct DB/LLM.
  lib/          # API client, auth helpers (token storage), formatting (currency/date), types.
```

Rules:
- `api/` MUST NOT import SQLAlchemy sessions directly (except via dependency that injects to repositories/services).
- `repositories/` MUST NOT import Groq, embeddings, or calculation policy.
- `services/` MUST NOT build HTTP responses; raise domain errors, let `api/` map them.
- Frontend `lib/api-client` is the ONLY module that calls backend; components never `fetch` ad hoc with secrets.
- Shared money formatting lives in ONE place per side (`backend/services/money.py`-concept, `frontend/lib/format.ts`-concept) — no inline currency math in components.

## 3. Backend Standards (Python + FastAPI)

- Python ≥ 3.11; type hints required on all public functions; `mypy`/`pyright`-clean intent (strict where feasible).
- FastAPI: dependency injection for `get_db`, `get_current_user`, `require_role(...)`, `resolve_tenant(...)`.
- Pydantic v2: `BaseModel` with `model_config = ConfigDict(...)` as needed; use `Decimal` for money, serialize money as string; datetimes timezone-aware UTC; reject unknown fields on inputs where appropriate (`extra="forbid"` for AI-ask and finance filters).
- SQLAlchemy 2.x style only: `select(...)`, `Mapped`, `mapped_column`; no legacy `query()` API.
- Config: `pydantic-settings` (or equivalent) reading env only; fail fast on missing required vars with safe message (never print values).
- Money: `Decimal` everywhere; define ONE rounding policy (e.g., `ROUND_HALF_UP`, 2 dp for display, full precision internally) in the calculation service; forbid `float` for money in new code.
- HTTP: use correct verbs/status (200/201/400/401/403/404/409/422/429/500/503). AI `insufficient_evidence` is a **200 with a typed body** (`status: "insufficient_evidence"`), NOT a 500.

## 4. Frontend Standards (Next.js + TS + Tailwind)

- TypeScript `strict: true`; no `any` without justification; API DTOs generated or mirrored from OpenAPI.
- Next.js App Router; distinguish server vs client components; secrets only in server-side env (and only non-sensitive public config exposed via `NEXT_PUBLIC_` — never keys).
- Tailwind for styling; no inline magic colors — use theme tokens; charts via a single chart library chosen at implementation (keep swappable).
- State: server state via fetch/SWR/React-Query-concept; auth token in `httpOnly` cookie preferred (or memory + refresh) — never in URL; tenant selection from backend `/me` membership.
- Every data view needs: `loading.tsx` / skeleton, `error.tsx` / retry, empty state. AI chat needs streaming-or-polling UX + citation rendering + `insufficient_evidence` callout.
- No authoritative logic: no role enforcement beyond hiding UI, no financial math beyond display formatting, no Groq/embedding/DB code.

## 5. Typed Interfaces & Contracts

- Backend DTOs are the contract. Breaking changes require doc update + frontend type update + test update in the same task.
- Error envelope (backend → frontend), mandatory shape:
  ```json
  { "error": { "code": "STRING_SNAKE", "message": "human-safe", "details": {}, "request_id": "uuid" } }
  ```
  `code` values are stable strings (e.g., `unauthorized`, `forbidden`, `not_found`, `validation_error`, `insufficient_evidence`, `tenant_mismatch`, `ingest_failed`, `llm_unavailable`, `db_unavailable`). Frontend switches on `code`, not message text.
- AI answer envelope (conceptual):
  ```json
  { "answer": "...", "route": "SQL|RAG|CALCULATION|HYBRID", "confidence": 0.0,
    "citations": [{"document_id":"...","page_number":1,"chunk_id":"...","snippet":"..."}],
    "status": "ok|insufficient_evidence|clarification_needed", "warnings": [] }
  ```

## 6. Structured Error Handling

- Backend: domain exceptions (`NotFound`, `Forbidden`, `TenantMismatch`, `ValidationFailed`, `InsufficientEvidence`, `LLMUnavailable`, `IngestFailed`) → mapped in one exception-handler module to HTTP + envelope. Never leak tracebacks, SQL, or secrets to clients; log full context server-side.
- Catch at boundaries only (API handlers, workers). No bare `except:`; no swallowing. Context managers for DB sessions (rollback on error).
- Financial edge cases are NOT exceptions-as-control-flow surprises: define behavior — division by zero → `undefined + reason`; missing period → `insufficient_evidence{missing:[...]}`; empty retrieval → `insufficient_evidence`, not empty answer.
- Frontend: typed `ApiError`; retry only idempotent GETs; POSTs (ask/upload) show actionable message + request_id for support.
- Workers: bounded retries with backoff; poison documents → `failed` status + error code, not infinite retry.

## 7. Structured Logging

- JSON logs (or key=value if JSON unavailable) with at minimum: `timestamp, level, request_id, user_id, company_id, route, latency_ms, error.code?`.
- Log at: request start/finish (info), auth failures (warn), routing decisions (info: route+confidence, no full prompt), ingest milestones (info), LLM calls (info: latency/tokens, never key/prompt at info), errors (error: code + safe context).
- NEVER log: secrets, JWTs, passwords, full document text, full prompts at info, embeddings vectors, DB connection strings.
- Correlation: `request_id` (UUID) generated at middleware, propagated to services/repos/workers and returned in error envelope.

## 8. Configuration & Environments

- Env-only config. Required backend vars (names conceptual, finalized at implementation): `DATABASE_URL`, `JWT_SECRET`, `GROQ_API_KEY`, `EMBEDDING_MODEL_NAME`, plus `APP_ENV`, `LOG_LEVEL`, `CORS_ORIGINS`.
- `.env` never committed (see `.gitignore`); `.env.example` with placeholder values only, added when implementation begins.
- Frontend: only `NEXT_PUBLIC_API_BASE_URL`-type public config in client; all secrets server-side.

## 9. Size, Naming, Style

- Files ~400 lines, functions ~50 lines (soft). Split by responsibility (e.g., `sql_executor` vs `hybrid_orchestrator`, not one `ai.py`).
- Names: explicit (`resolve_tenant_company_id`, not `get_cid`; `compute_yoy_growth`, not `calc2`). No single-letter vars except loop indices.
- Python: `ruff` (or black+isort equivalent) + type check; TS: `eslint` + `tsc --noEmit`. CI must run lint + types + tests.
- Comments explain WHY, not WHAT. No dead code, no commented-out blocks, no TODO without issue ref.

## 10. Dependencies & Security Hygiene

- Pin versions (lockfile). Prefer stdlib / framework features over new libs.
- No frontend bundle inclusion of backend-only libs (Groq SDK, SentenceTransformers, SQLAlchemy, pgvector driver).
- `pip audit` / `npm audit` awareness; update path documented when CVEs arise.

## 11. What Belongs Where (Quick Reject List)
| If you are about to ... | Put it in ... | NOT in ... |
|--------------------------|---------------|-------------|
| Write SQL / vector query | `repositories/` | `api/`, frontend |
| Compute YoY/margin/ratio | `services/calculation*` | LLM prompt, frontend, repository |
| Call Groq | `services/llm*` (backend only) | frontend, repository, router |
| Decide SQL vs RAG | `services/router*` | executors, api |
| Format currency for display | `lib/format` (frontend) / money DTO (backend) | LLM output parsing |
| Enforce role/tenant | backend middleware/service/repo | frontend alone |

## 12. Change Discipline (Per AGENTS.md §13)

1. Surgical changes only: touch exactly the files required by the task. No opportunistic refactors, no formatting churn, no "improvements" to adjacent code.
2. No unrelated file modifications. If unrelated dead code or a bug is found, REPORT it (under `### Remaining`) — do not fix it silently in the same change.
3. Remove only dead code introduced by your own change (orphaned imports/variables/functions from your edit).
4. Match existing style in the touched files, even where personal preference differs.
5. Every changed line MUST trace to the user request (see `karpathy-guidelines` skill §3). If it doesn't, revert it.

## 13. Documentation Expectations

1. Code comments explain WHY, not WHAT. No commented-out code blocks. No TODO without an owner/issue reference.
2. When a change alters an HTTP contract, DB schema, auth behavior, routing behavior, or calculation semantics, the matching rule doc (`ARCHITECTURE.md` / `DATABASE_RULES.md` / `RAG_RULES.md` / `SECURITY_RULES.md` / `TESTING_RULES.md`) MUST be updated in the same task — or an explicit `### Remaining` entry MUST explain why the doc update is deferred.
3. Never duplicate all of `AGENTS.md` into domain docs; cross-reference it (`AGENTS.md` §2 authority, §7 backend boundary, §8 calculation rule, §9 grounding rule, §11 database rule) and keep domain detail local.
4. Implementation responses end with the `### Changed / ### Tests / ### Validation / ### Remaining` report per `AGENTS.md` §15 — no exceptions for code tasks.
