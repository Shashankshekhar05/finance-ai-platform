# DATABASE_RULES.md — PostgreSQL + pgvector + Alembic

> Status: NORMATIVE (subordinate to `AGENTS.md` + `ARCHITECTURE.md` + `SECURITY_RULES.md`).
> Defines schema shape, tenancy enforcement, vector rules, and migration discipline. No DDL code here — only contracts implementation must satisfy.

## 1. Principles

1. PostgreSQL is the ONLY primary database. pgvector is the ONLY vector index. No FAISS/Chroma/Pinecone sidecar.
2. All schema change via Alembic migrations. `Base.metadata.create_all()` is FORBIDDEN in application startup, API handlers, workers, and tests that run against shared DBs (tests may create isolated schemas/fixtures explicitly — see `TESTING_RULES.md`).
3. Every financial or document row is tenant-scoped by `company_id`, enforced in the DB access layer on EVERY query — including vector similarity search.
4. Money uses exact numerics; vectors use `vector(768)` exactly; time uses timestamptz.
5. Auditability over convenience: append-only logs, status machines on ingestion, foreign keys everywhere.

## 2. Extensions & Types

- Required extension: `pgvector` (`CREATE EXTENSION IF NOT EXISTS vector;` in a migration, not in app code).
- Embedding column type MUST be `vector(768)` — matching `BAAI/bge-base-en-v1.5`. Changing dimension or model requires human approval (locked decision) + full re-embedding migration.
- Money: `NUMERIC(18,2)` (or `NUMERIC` with service-level rounding policy) — NEVER `FLOAT/REAL/DOUBLE PRECISION` for money. Percentages/ratios computed in Python `Decimal`, stored as `NUMERIC` where persisted.
- Time: `TIMESTAMPTZ` (UTC) for all timestamps; `DATE` for accounting periods. IDs: UUID PKs (`gen_random_uuid()`) for all domain tables; FKs indexed.
- Text search (optional later): pg_trgm / tsvector allowed as complement, never as vector replacement.

## 3. Domain Entities (Logical Schema)

All tables include `id UUID PK`, `company_id UUID NOT NULL FK → companies.id` (except `companies` itself and global `users`; see §4), `created_at TIMESTAMPTZ DEFAULT now()`, `updated_at TIMESTAMPTZ` where mutable. Additional columns per entity:

| Entity | Purpose | Key fields (conceptual) |
|--------|---------|--------------------------|
| `companies` | Tenant root | `name UNIQUE, slug UNIQUE, status, settings JSONB` |
| `users` | Identity (global, can belong to many companies) | `email UNIQUE CITEXT, password_hash, display_name, status, last_login_at` |
| `user_roles` | Membership + RBAC join | `user_id FK, company_id FK, role: viewer\|analyst\|admin, granted_by, UNIQUE(user_id, company_id, role)` |
| `documents` | Uploaded financial docs | `company_id FK, title, filename, mime_type, byte_size, sha256, status: pending\|processing\|ready\|failed, error_code?, uploaded_by FK users, ingested_at?` |
| `document_pages` | Page-level split | `document_id FK, company_id (denorm), page_number INT, width?, height?, char_count?, content_types TEXT[]` |
| `document_chunks` | Retrievable units + vectors | `document_id FK, page_id FK?, company_id (denorm), chunk_index INT, content_type: text\|table\|visual_caption, text TEXT, embedding vector(768), token_count INT, bbox JSONB?, table_ref JSONB?` |
| `revenue` | Structured revenue lines | `company_id FK, period DATE, amount NUMERIC(18,2), currency CHAR(3), segment?, source?, UNIQUE(company_id, period, segment)` |
| `expenses` | Structured expense lines | `company_id FK, period DATE, amount NUMERIC(18,2), currency, category, UNIQUE(company_id, period, category)` |
| `transactions` | Granular journal-ish rows | `company_id FK, occurred_at TIMESTAMPTZ, amount NUMERIC(18,2), currency, kind, counterparty?, description?, UNIQUE(company_id, occurred_at, amount, description)` (dedupe-tolerant) |
| `financial_metrics` | Precomputed/verified KPIs | `company_id FK, period DATE, metric_name (e.g., gross_margin, yoy_growth), value NUMERIC, unit, computed_by: system\|import, inputs_ref JSONB, UNIQUE(company_id, period, metric_name)` |
| `ai_conversations` | Chat threads | `company_id FK, user_id FK, title?, created_at` |
| `ai_messages` | Q&A records | `conversation_id FK, company_id (denorm), role: user\|assistant\|system, content TEXT, route?: SQL\|RAG\|CALCULATION\|HYBRID, confidence FLOAT?, citations JSONB?, evidence_refs JSONB?, status: ok\|insufficient_evidence\|clarification_needed\|error, latency_ms?` |
| `audit_logs` | Append-only | `company_id FK NULLABLE (null only for global auth events), actor_user_id FK?, action, entity_type?, entity_id?, metadata JSONB, created_at` — NO updates/deletes via app. |

Notes:
- `company_id` is denormalized onto `document_pages`, `document_chunks`, `ai_messages` to allow single-filter tenant isolation on vector + history queries without joins.
- `citations JSONB` shape: `[{document_id, page_number, chunk_id, snippet?}]`. `evidence_refs`: `{sql_row_ids?, chunk_ids[], calc_inputs[]}`.
- Currencies: ISO-4217; single-currency-per-company in v1 unless explicitly modeled with FX (deferred — see §8 ambiguities).

## 4. Tenancy Rules (Hard Requirements)

1. `companies.id` is the tenant boundary. All queries in §3 tables with `company_id` MUST filter `WHERE company_id = :cid` with `:cid` from the validated JWT — never from client-supplied body alone.
2. Vector search MUST include the tenant predicate BEFORE/with similarity ordering, e.g. conceptually `WHERE company_id = :cid ORDER BY embedding <=> :q LIMIT k`. Unscoped nearest-neighbor search is forbidden.
3. `users` are global; access is via `user_roles(company_id, role)`. A request with no matching `user_roles` row for the requested `company_id` → `403 tenant_mismatch` + audit log.
4. Admin cross-company reads allowed ONLY on explicitly marked audit/admin repository methods, each emitting an `audit_logs` row with `actor, action, target_company_id`.
5. No shared/demo company with relaxed isolation. Demo data is a normal tenant (e.g., `demo-acme`) with the same enforcement.

## 5. pgvector Rules

1. Column: `document_chunks.embedding vector(768) NOT NULL`.
2. Embeddings MUST be L2-normalized at write (and query vectors normalized identically) so cosine semantics are stable; document the normalization in the embedding service.
3. Index: HNSW (preferred for recall/latency) or IVFFlat — chosen at implementation with a migration + brief benchmark note; MUST be created in a migration with `USING hnsw (embedding vector_cosine_ops)` (or equivalent) and must include tenant-filtering strategy (partial index per large tenant OR filtered query — document choice).
4. Retrieval MUST set a similarity/distance cutoff + `LIMIT` (defaults e.g., `k=8`, tunable) and return distance scores for rerank/threshold logic. No unbounded vector scans in request path.
5. Model pinning: record `embedding_model` + `embedding_model_revision` on `documents` (or a dedicated `embedding_versions` concept) so re-embedding on model change is detectable. Mixed-version vectors in one index are forbidden without a migration.

## 6. Alembic Discipline

1. Every schema change = new Alembic revision with `upgrade()` + `downgrade()`; message names imperative (`add_share_class_to_documents`); one logical change per revision.
2. Migrations must: enable `pgvector` extension (first vector migration), use `IF NOT EXISTS`-safe patterns where appropriate, backfill `company_id` denorm columns, build indexes `CONCURRENTLY` on large tables (with `transaction: off` note where needed).
3. App startup MUST NOT call `create_all()`, MUST NOT auto-run `upgrade head` silently in web process (run migrations as a separate deploy job / entrypoint step). Startup checks may VERIFY connectivity + extension presence (read-only) and fail fast with safe error.
4. Seed data (demo company, demo user, sample financials) lives in EXPLICIT seed scripts/fixtures run manually or in CI — never in migrations that insert business data silently (enum/reference inserts excepted with justification).
5. CI must: run `alembic upgrade head` on ephemeral Postgres, then run DB tests, then `downgrade -1 / upgrade head` smoke on at least one revision chain.

## 7. Integrity, Indexing, Retention

- FKs: `ON DELETE CASCADE` for `document_pages/chunks → documents`; `RESTRICT` for financial facts (never cascade-delete money); `SET NULL` only for `audit_logs.actor` (preserve log on user delete).
- Unique guards: dedupe uploads by `(company_id, sha256)` (warn, don't silently drop); financial uniqueness per §3 to prevent double-count on re-import.
- Indexes: btree on all FKs + `(company_id, period)` for finance; GIN on `audit_logs.metadata` / `ai_messages.citations` only if queried; HNSW/IVFFlat on embeddings per §5.
- PII/minimization: `ai_messages.content` retention policy documented (e.g., purge demo threads after N days — decided at implementation); `audit_logs` retained longest, immutable.
- No soft-delete for money without `voided_at + voided_by + reason` pattern; hard deletes of financial rows require `admin` + audit row.

## 7A. Transactions & Session Boundaries (SQLAlchemy 2.x)

1. One request (or one worker job) = one session/transaction scope, managed by FastAPI dependency (`get_db`) or worker context manager. Repositories NEVER hold global sessions; services NEVER commit from inside loops over unflushed reads.
2. Default isolation: READ COMMITTED. Escalate to REPEATABLE READ / SERIALIZABLE only for explicit money-write paths (imports, metric recomputation) with a comment justifying why — never globally.
3. Write ordering: validate → authorize → scope tenant → mutate → flush → emit audit row IN THE SAME transaction where the audited mutation occurs (audit write fails ⇒ whole mutation rolls back). Cross-transaction audit (audit succeeds, mutation lost) is forbidden.
4. Ingestion writes (document → pages → chunks) commit as ONE transaction per document (or per page-batch with idempotent resume keys) — never one commit per chunk without a resume/status guard; failed batches leave `documents.status=failed` + `error_code`, never half-`ready`.
5. Financial imports: all-or-nothing per import batch (rollback on any row violation); re-import of the same `(company_id, period, segment/category)` keys MUST be idempotent via unique guards + explicit upsert policy documented in the migration/service — never silent double-count.
6. No autocommit in app code; no nested-commit tricks. On ANY exception: rollback, map to the typed error envelope (see `DEVELOPMENT_RULES.md` §5–§6), log with `request_id`. Connection-pool checkout failures → `503 db_unavailable`, never a partial response.

## 8. Out of Scope / Deferred (Must Not Be Assumed)

- Multi-currency consolidation + FX tables; row-level security (RLS) policies (enforcement is at repository layer in v1 — RLS may be added later as defense-in-depth, not as replacement); table partitioning; read replicas.

## 9. Finance Domain Decisions (Phase 3 — Normative for Implemented Tables)

1. **Precision/scale**: line amounts (`revenue`, `expenses`, `transactions`) are `NUMERIC(18,2)`; `financial_metrics.value` is `NUMERIC(24,8)` (ratios/margins need >2dp). API layer serializes both as exact strings — never float.
2. **Single-sign convention**: all stored amounts are positive (`CHECK amount > 0`); direction comes from structure (`transactions.type`, table choice), never from a sign.
3. **Currency**: stored per row as a 3-letter code (shape-validated, uppercased). v1 assumes one primary currency per company; NO conversion is performed anywhere. Multi-currency consolidation requires an explicit architecture change.
4. **Fiscal fields**: `fiscal_year`/`fiscal_quarter` are explicit inputs only, guarded by `quarter-requires-year` CHECKs. No company fiscal-calendar configuration exists yet, so NOTHING derives fiscal periods from calendar dates. Adding one is an explicit architecture change.
5. **Uniqueness**: the only business unique is `financial_metrics(company_id, period, metric_name)` (all NOT NULL, fully effective; upsert-on-recompute). `revenue`/`expenses`/`transactions` carry no business unique: their natural keys contain nullable dimensions and PostgreSQL treats NULLs as distinct, so a unique would silently fail to dedupe. Import-time dedupe keys belong to the documents/import phase, not manual CRUD.
6. **Money FKs are RESTRICT**: `companies` rows with financial facts cannot be deleted (no cascade-deletes of money). Deletes of facts are hard deletes, admin-only, until `audit_logs` exists to record them.
7. **Source traceability**: `source_document_id` (UUID, no FK) + `source_page` are nullable stubs. The FK to `documents` is added in the documents phase — never invent references before then.

## 10. Document Domain Decisions (Phase 4 — Normative for Implemented Tables)

1. **Status vocabulary**: `documents.status` is `uploaded | processing | indexed | failed`. This DIVERGES from the `pending | processing | ready | failed` names used in RAG_RULES §2.1 and §3 of this file (both written before any document code existed). The Phase 4 task spec names the former explicitly ("suggested states"); implemented as specified. Alignment plan (docs + enum rename, no data loss — statuses are VARCHAR): reconcile to ONE vocabulary when the chunking phase lands; until then §10 governs `documents`, RAG_RULES §2.1 governs future chunks.
2. **No `document_chunks` yet**: pages carry `extracted_text` + detection flags + table summaries. Chunking (with embeddings) is a later phase and owns cell-level table serialization.
3. **Bytes live outside Postgres**: `documents.storage_key` references the StorageService object; no binary columns exist. Local backend is `LocalFileStorage` under `DOCUMENT_STORAGE_ROOT`.
4. **Finance `source_document_id` stays FK-less**: adding that constraint belongs to financial reconciliation (explicitly out of Phase 4 scope). The columns remain nullable stubs.
5. **Ingestion commits twice per upload by design** (document row, then pages + terminal status) so `failed` rows with typed codes persist for retry. This is the documented exception to §7A.1's one-scope rule; each step is internally atomic.
6. **Page FKs**: `document_pages.document_id → documents.id` is CASCADE (pages are part of the document); both tables' `company_id → companies.id` is RESTRICT (tenant rows with documents cannot vanish).

## 11. Retrieval Domain Decisions (Phase 5 — Normative for Implemented Behavior)

1. **Status reconciliation (canonical)**: `documents.status` stays `uploaded | processing | indexed | failed`, where **`indexed` means pages-parsed only — never vectors**. Vector readiness lives on `documents.embedding_status` (`pending | indexing | ready | failed`) + `embedding_model` + `chunk_count`. Only `embedding_status = ready` means retrievable. This resolves the Phase 4 divergence note in §10: no enum rename was needed; the two dimensions compose instead of competing.
2. **Single-page chunks**: `document_chunks` carries `page_id` + denormalized `page_number` directly — no `chunk_pages` join table. Justification: RAG_RULES §3.1 forbids cross-page merges, so a chunk can never span pages; the simplest correct provenance is columns, not a graph.
3. **Vector column/index**: `embedding vector(768)` NOT NULL (pgvector `Vector` type, not raw DDL) + HNSW index `ix_chunks_embedding_hnsw` with `vector_cosine_ops`, default build params (m=16, ef_construction=64 as shipped). Declared in model metadata so `alembic check` stays drift-free. Correctness first at current scale; retune only with measured recall/latency data.
4. **Chunk FKs**: `company_id → companies` RESTRICT; `document_id → documents` and `page_id → document_pages` CASCADE (chunks die with their document). Business unique is `(document_id, chunk_index)` — positional identity enabling delete/rebuild convergence.
5. **Btree support**: `company_id`, `(company_id, document_id)`, `(company_id, page_number)` — each backs an actual query path (tenant scope, per-doc rebuild/count, page filter). Nothing speculative.

## 12. Conversation Domain Decisions (Phase 9 — Normative for Implemented Tables)

1. **Two tables, no more**: `conversations` (owner + company + optional title) and `conversation_messages` (append-only log). No route metadata, no token/secret/system columns — unneeded persistence is rejected, not deferred.
2. **Ordering by explicit sequence**: `UNIQUE(conversation_id, sequence)` plus a parent-row `FOR UPDATE` lock on append. `created_at` is informational; sequence is the order. Best-effort serialization, documented as such.
3. **FKs mirror domain gravity**: message→conversation CASCADE (thread delete removes messages and nothing else); conversation→company and message→company RESTRICT (tenant history blocks silent tenant deletion); message→user none (ownership lives on the thread, keeping the log shape minimal); conversation→user CASCADE.
4. **Role CHECK (`user|assistant`)** at the DB layer so no system/token/secret content type can exist even if service discipline lapses.
5. **Btree support**: `(company_id, user_id)` + singles (ownership listing), `(conversation_id, sequence)` (window reads). Each backs an implemented query.
