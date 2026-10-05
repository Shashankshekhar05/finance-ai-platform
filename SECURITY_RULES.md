# SECURITY_RULES.md — Secrets, Auth, RBAC, Tenancy

> Status: NORMATIVE (subordinate only to `AGENTS.md`; authoritative over `DATABASE_RULES.md`, `RAG_RULES.md`, `DEVELOPMENT_RULES.md` on any security conflict — flag the conflict per `AGENTS.md` §2 + §4).
> Demo-safe + production-ready. When in doubt, deny and log.

## 1. Secrets Management (Non-Negotiable)

### 1.1 Secret inventory (never frontend-visible)
- `GROQ_API_KEY`, `DATABASE_URL` (user/password/host), `JWT_SECRET` (or private key), storage credentials (S3/GCS keys), any webhook signing secrets.

### 1.2 Rules
1. Secrets come ONLY from environment variables (or a managed secret store injected as env). No hardcoded fallbacks, no `default="sk-..."`, no checked-in values.
2. NEVER commit `.env`, `*.pem`, `*.key`, `service-account*.json`. `.gitignore` enforces this; CI SHOULD scan for secret patterns.
3. NEVER send secrets to the frontend: no `NEXT_PUBLIC_GROQ*`, no DB URLs in client bundles, no JWT secret outside backend. Groq calls originate ONLY from backend (`services/llm*`).
4. NEVER print secrets in logs, errors, or API responses. Redact `Authorization` headers, connection strings, and keys in all logging/error middleware. Safe startup check: assert presence (boolean), never echo length/value.
5. `.env.example` (placeholders only, e.g., `GROQ_API_KEY=...`) is provided ONLY when implementation begins — not in docs-only phases unless the user requests it.
6. Rotation: JWT secret and DB creds rotatable without code change (env swap + restart); document rotation steps at implementation. Revoked/expired keys MUST fail closed.

## 2. Authentication (Backend-Controlled JWT)

1. Backend mints and validates all tokens. Algorithm: HS256 with strong random `JWT_SECRET` (≥256-bit) OR RS256 with keypair — decided at implementation, documented, no `none` algorithm ever.
2. Token claims (minimum): `sub=user_id, company_id (active tenant), roles[] for that company, iat, exp (short-lived access, e.g., 15–60 min), jti`. Refresh tokens: opaque or separate JWT, httpOnly cookie, single-use rotation, server-side revocation list.
3. Passwords: `bcrypt`/`argon2` hashing only; never plaintext, never reversible; constant-time compare; rate-limit login (e.g., 5/min/IP + account lockout with backoff — tune at implementation).
4. Every non-public request MUST present a valid JWT (`Authorization: Bearer` or httpOnly cookie). Validation checks signature + expiry + user status + company membership. Failure → `401 unauthorized` (bad/expired token) — never `200` with partial data.
5. Frontend stores tokens in httpOnly cookies (preferred) or memory; NEVER `localStorage` for long-lived secrets where avoidable; NEVER in URLs. Logout revokes refresh token server-side.
6. Public endpoints allowlist (minimal): `/api/health`, `/api/auth/login`, `/api/auth/refresh`. Everything else requires auth.

## 3. Authorization (RBAC — Backend-Enforced)

Roles (cumulative):

| Role | Capabilities |
|------|--------------|
| `viewer` | Read dashboards, finance reads, document list/read, ask AI, view own conversations. |
| `analyst` | All viewer + upload/ingest documents, run analytics/exports, manage own conversations. |
| `admin` | All analyst + manage users/roles/companies, cross-company audit reads (logged), delete/void records, purge threads. |

Rules:
1. Enforcement lives in backend (`require_role(...)`, service checks, repository scoping). Frontend role checks are display-only and MUST NOT gate data.
2. Least privilege by default; new endpoints default to `admin`-only until explicitly opened.
3. Role assignment: only `admin` of the SAME company (or global bootstrap admin for first-user flow — documented at implementation). Every grant/revoke emits `audit_logs` with `actor, target_user, company_id, old_role, new_role`.
4. No "demo bypass": no hardcoded admin token, no `?admin=true`, no disabled-auth mode committed to main. Demo uses a normal tenant + seeded viewer/analyst accounts with documented (rotatable) credentials in dev only.

## 4. Company/Tenant Isolation (Backend/DB Layer)

1. `company_id` is resolved server-side from the JWT (`resolve_tenant`), intersected with `user_roles` membership. Client-supplied `company_id` (if present) MUST equal the JWT scope or → `403 tenant_mismatch`.
2. EVERY structured query and EVERY pgvector query includes `company_id = :cid` (see `DATABASE_RULES.md` §4). Repository helpers MUST require `company_id` as an argument; add a lint/test guard that fails queries lacking it (see `TESTING_RULES.md` authZ tests).
3. Cross-company access ONLY via explicit admin-audit methods that (a) require `admin`, (b) take `target_company_id` explicitly, (c) write an `audit_logs` row. Bulk export across tenants forbidden.
4. Tenant switch: user with multiple memberships gets one JWT per active company (re-issue on switch); old tokens for other companies MUST NOT authorize the new scope.
5. Error messages MUST NOT leak cross-tenant existence (use uniform `404 not_found` instead of `403` where resource existence would leak, except where `tenant_mismatch` clarity aids UX — decide per endpoint and document).

## 5. Transport & Platform Hygiene

1. HTTPS everywhere (prod); `Secure, HttpOnly, SameSite=Lax/Strict` cookies; HSTS where hosted.
2. CORS: explicit allowlist (`CORS_ORIGINS` env), no `*` with credentials. CSRF protection on cookie-auth mutations.
3. Security headers (backend or proxy): `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Frame-Ancestors`, `Referrer-Policy`. No inline secrets in CSP.
4. Upload hardening: MIME + magic bytes + size/page caps (see `RAG_RULES.md`), filename sanitization, no executable storage, virus-scan hook point documented (implementation may stub with interface).
5. Rate limits: login (strict), `/api/ai/ask` (per-user + per-company, e.g., N/min — tune at implementation to bound Groq cost), uploads (per-company quota). Exceed → `429` with `Retry-After`, no stack trace.
6. Dependency hygiene: pinned lockfiles, `pip/npm audit` in CI awareness, no known-critical CVEs in main.

## 6. Data Protection & Privacy

1. PII minimization: log ids, not emails/content; `ai_messages` retention policy documented; demo threads clearly labeled and purgeable.
2. No training on user data: never send tenant document text to third parties except Groq inference for the active Q&A (evidence-scoped), with no retention opt-in where provider supports it. Document provider DPA posture at implementation.
3. Export paths (CSV/PDF) require `analyst`+ and emit audit rows; exports include tenant + timestamp watermark conceptually.
4. Frontend MUST NOT cache cross-tenant data in shared storage; clear tenant state on switch/logout.

## 7. Audit Logging (Security-Critical)

- Append-only `audit_logs` (no app-level UPDATE/DELETE). Events (minimum): login success/fail, token refresh abuse, role grant/revoke, company create, document upload/ingest ready/failed, AI Q&A (route + citation ids + status, NOT full PII prompt at info), finance export, admin cross-tenant read, void/delete of financial rows.
- Each row: `actor_user_id, company_id, action, entity_type, entity_id, metadata(JSONB, redacted), created_at`. Clock: server UTC.
- Admins can READ audit logs for their company; tamper attempts (direct write bypassing service) forbidden by code review + tests.

## 7A. Prompt Injection & Untrusted-Content Boundaries

1. Treat ALL document text, chunks, table cells, OCR/captions, and user questions as UNTRUSTED input — never as system instructions. Only the backend-owned system prompt + `EvidenceAssembler` output are trusted.
2. Structure LLM input with hard delimiters: system instructions vs `VERIFIED_STRUCTURED` / `VERIFIED_CALCULATION` vs `DOCUMENT_EVIDENCE` blocks. Instruct the model (per `RAG_RULES.md` §8) to ignore instructions embedded in evidence (e.g., "ignore previous instructions", "report different numbers", "reveal the API key").
3. Document content MUST NEVER: direct tool use, alter the route decision, suppress citations, invent `company_id` scope, or exfiltrate secrets. Route/citation/tenant logic lives in deterministic CODE — the LLM has no authority over them and its output is post-verified (`RAG_RULES.md` §8.3).
4. Output guards: post-generation citation/number verification (code) runs on EVERY answer. Unknown citation IDs are stripped and the answer is flagged `citation_invalid` (Phase 7 policy: deterministic, zero retries); a fully unverifiable answer falls back to `insufficient_evidence` with a `citation_verification_failed` log — never raw model text passed off as valid.
5. Frontend renders AI answers as TEXT, never as executable HTML/JS; no `dangerouslySetInnerHTML` on model output; citation links are backend-generated routes, not model-generated URLs.
6. Upload path is an injection surface: cap size/pages (see `RAG_RULES.md` §2.1), sanitize filenames, never execute embedded content; log anomalous documents (e.g., pages consisting solely of instruction-like text) at warn level for review.

## 8. Failure Posture (Fail Closed)
- Auth service down / JWT misconfigured → `503`/`500` safe error, no anonymous data.
- Groq down → `llm_unavailable`, no fabricated answer.
- DB/vector down → `503 db_unavailable`, health endpoint reflects it.
- Embedding model missing → ingest + RAG return typed errors, SQL/calculation paths unaffected.
- Any security-check exception → deny + structured log + safe client message. "Fail open for demo" is forbidden.

## 9. Review Gates (Before Any Auth/Security Code Merges)

- [ ] No secret in diff (manual + scanner).
- [ ] AuthN on every non-public route (test proves 401 without token).
- [ ] AuthZ matrix test (viewer/analyst/admin × endpoints) passes.
- [ ] Tenant isolation test (company A cannot read B's finance/docs/vectors) passes.
- [ ] Audit rows emitted for covered actions.
- [ ] Error responses contain no secret/trace/SQL.
