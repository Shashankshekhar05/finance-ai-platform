# TESTING_RULES.md — Test Pyramid, Fixtures, Gates

> Status: NORMATIVE (subordinate to `AGENTS.md`; interprets all other rule files for verification).
> Principle: a feature is NOT done when the app starts — it is done when implemented + tested + validated + error-handled + documented (per `AGENTS.md` §12 + §15).

## 1. Test Pyramid (Required Layers)

| Layer | Scope | Tools (concepts) | Gate |
|-------|-------|------------------|------|
| Unit | Pure logic: calculations, router, evidence assembly, money formatting, chunking | `pytest` / `vitest` | Must pass; calc tests deterministic |
| API | HTTP contracts: status, envelope, authN/Z, validation, tenant scoping | `pytest + httpx/TestClient` (backend), `vitest + MSW`-concept (frontend) | Must pass; no 500 on bad input |
| Database | Migrations, constraints, pgvector round-trip, tenant filters | `pytest` vs ephemeral Postgres+pgvector, Alembic upgrade/downgrade | Must pass on `upgrade head` |
| AuthN/Z | Login, JWT, RBAC matrix, tenant isolation (structured + vector) | API tests with fixture users/companies | Must pass; 401/403 exact |
| RAG retrieval | Recall@k, citation precision, tenant-leak = 0, insufficient_evidence behavior | Fixture docs + fixed embeddings or recorded vectors | Must pass |
| Routing | Route accuracy on labeled set; confidence calibration; low-conf fallback | Labeled Q&A fixture | Accuracy gate (see §5) |
| Calculation | Deterministic fixtures: YoY, margins, aggregates, edge cases | Fixed CSV/JSON fixtures, `Decimal` exact compare | 100% pass, no float |
| Ingestion | PDF → pages → chunks → vectors; table/visual paths; failure modes | Sample PDFs (tiny, committed) + synthetic | Must pass incl. failures |
| Frontend | Component + flow: loading/error/empty, citations render, insufficient callout | `vitest` + `playwright`-concept (smoke) | Smoke pass pre-demo |

Every meaningful feature MUST add or extend tests in at least its primary layer + API layer where it touches HTTP.

## 2. Layout & Conventions

- Backend: `backend/tests/{unit,api,db,rag,routing,calc,ingest}/test_*.py`; shared `conftest.py` with fixtures (never production creds).
- Frontend: `frontend/__tests__/` or colocated `*.test.ts(x)`; contract tests mirror backend OpenAPI DTOs.
- Naming: `test_<unit>_<behavior>` (e.g., `test_yoy_growth_zero_base_returns_undefined`). One behavior per test; arrange-act-assert.
- Determinism: seed RNG; freeze time (`freezegun`-concept); pin embedding model revision in RAG tests (or use precomputed vectors to avoid model download in CI).
- No network in unit tests: mock Groq client with recorded fixtures; no live Groq in CI by default (nightly live-smoke optional, manual).

## 3. Fixtures (Canonical, Reused)

1. **Tenants/users**: `company_a`, `company_b`, `demo_acme`; users `viewer_a`, `analyst_a`, `admin_a`, `viewer_b` (cross-tenant negative). JWTs minted via test `AuthService`, short expiry.
2. **Finance data**: fixed `revenue/expenses/transactions` rows for 2023–2025 (two segments, two categories) with KNOWN totals; expected YoY/margin values precomputed by hand in fixture file.
3. **Documents**: (a) tiny 2-page text PDF with known sentences, (b) 1-page table PDF with known figures, (c) 1-page chart-image PDF with known caption; each with expected `page_numbers`, chunk counts, and ground-truth Q&A pairs.
4. **Routing set**: ≥ 24 labeled questions (≥6 per route) including the canonical four routes defined in `ARCHITECTURE.md` §7 (SQL / RAG / CALCULATION / HYBRID) + ambiguous/low-context cases expecting `HYBRID` or `clarification_needed`.
5. **Error fixtures**: malformed PDF, oversized upload, missing period query, zero-base YoY, expired JWT, cross-tenant access attempts.

## 4. Specialty Suites (What Must Be Tested)

### 4.1 Calculation tests (deterministic, highest weight)
- YoY/QoQ growth, gross/net margin, totals, averages over fixtures; assert `Decimal` exact equality (string compare).
- Edge cases (each its own test): zero-division → `undefined + reason`; missing period → `insufficient_evidence{missing}`; negative values; rounding policy (HALF_UP, 2dp display); currency mismatch → error, never silent convert.
- Property: LLM output NEVER feeds calculation inputs (test the wiring: calc service takes repository rows, not LLM text).

### 4.2 Routing tests
- Labeled-set accuracy gate (initial bar, e.g., ≥ 85% — ratchet upward, never downward without approval).
- Confidence: low-info questions → `confidence < threshold` + `HYBRID` or `clarification_needed`; router output schema-validated (`route, confidence 0..1, rationale non-empty, slots`).
- Separation: executors import no router internals (static import test or review check).

### 4.3 RAG retrieval tests
- Recall@k on fixture docs (known question → expected chunk in top-k); citation precision (every cited chunk in evidence set); page-number fidelity.
- Tenant-leak test: query as `company_a` MUST NOT retrieve `company_b` chunks (assert 0 cross-hits over repeated runs).
- Threshold test: nonsense query → 0 kept hits → `insufficient_evidence`, no LLM facts.
- Table test: figure-seeking query prefers TABLE chunk; visual test: chart question cites `visual_caption` marked low-trust.

### 4.4 Ingestion tests
- Happy paths per content type (text/table/visual) asserting page rows, chunk metadata, `vector(768)` dims, normalized embeddings.
- Failures: corrupt PDF → `failed + error_code`; oversized → `413/422`; duplicate sha → idempotent `duplicate: true`.
- Idempotency: re-ingest same sha → no duplicate chunks.

### 4.5 AuthN/Z + tenancy tests
- Matrix: each role × each endpoint group → exact expected status (200/201 vs 401/403). Viewer cannot upload; analyst cannot manage roles; admin can (same company only).
- Tenant isolation: A-token reading B-company finance/docs/vectors/chat → `403/404` per contract + audit row; B-data never in payload.
- JWT: expired/tampered/missing → `401`; wrong `company_id` claim vs path → `403 tenant_mismatch`.

### 4.6 API + DB tests
- Contract: error envelope shape on all failures; money serialized as string; datetimes UTC ISO.
- DB: `alembic upgrade head` clean; FK/unique violations surfaced as typed errors (not 500 tracebacks); vector round-trip (insert → search → find own chunk); downgrade/upgrade smoke.

## 5. Quality Gates (CI Must Enforce)

- `lint + types + unit + api + db` green on every PR. RAG/routing/calc suites green; nightly may add heavier eval.
- Coverage: overall ≥ 80% backend new-code intent; calculation + authZ modules ~100% on branches that touch money/access.
- No test that asserts "app starts" as proof of correctness. Every PR touching finance/RAG/auth MUST cite the specialty suite run.
- Flaky policy: quarantine + issue link; no `@skip` without expiry/owner. Vector tests MUST NOT be flaky-by-threshold — fix cutoff/seed instead.
- Secrets scan + `.env` absence check in CI.

## 6. Validation (Manual, Per Feature — Reported Under `### Validation`)

Beyond automated tests, the implementer MUST run and report:
- Backend boot + `alembic upgrade head` on ephemeral DB (paste command + result).
- Happy-path curl/HTTPie calls with expected JSON (redacted tokens).
- Frontend flows: dashboard load, ask (each route once), upload, error/empty states (screenshot or step list for demo features).
- Failure drills: Groq unreachable (mocked), DB down (health reflects), bad upload, cross-tenant attempt — each showing typed error, not traceback.

## 7. Reporting (Per AGENTS.md §15)

Implementation responses MUST use `### Changed / ### Tests / ### Validation / ### Remaining`, where `### Tests` names suites + counts + pass/fail (e.g., "calc: 18/18 pass; rag tenant-leak: pass; routing accuracy 22/24").

## 8. Regression Testing

1. Every bug fix MUST add a regression test reproducing the bug BEFORE the fix (fail-first), kept permanently in the relevant suite.
2. Protected regression surfaces (always re-run on related changes): routing labeled set, calculation fixtures, tenant-isolation matrix, ingestion idempotency, migration upgrade/downgrade smoke.
3. Accuracy/threshold gates (routing accuracy, retrieval recall@k) MUST never be lowered to make a suite pass — lowering a gate requires human approval with written rationale.
4. Flaky-test quarantine requires an issue link + owner + expiry; quarantined tests still run in nightly, never silently deleted.

## 9. Definition of Done (Per AGENTS.md §12 + §15)

A task is complete ONLY when ALL hold:
- [ ] Implementation matches the architecture + domain rules.
- [ ] New/updated tests in the primary layer(s) + API layer where HTTP is touched — all passing.
- [ ] `lint + types + full relevant suites` green; failures reported honestly, never hidden.
- [ ] Manual validation performed (§6) and reported under `### Validation`.
- [ ] Error handling + structured logging added for new failure paths.
- [ ] Docs updated if contracts/schema/behavior changed; otherwise an explicit `### Remaining` entry explains the deferral.
- [ ] Final response uses the `### Changed / ### Tests / ### Validation / ### Remaining` format.
