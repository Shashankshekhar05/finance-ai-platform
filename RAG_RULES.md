# RAG_RULES.md — Retrieval-Augmented Generation Contract

> Status: NORMATIVE (subordinate to `AGENTS.md` + `ARCHITECTURE.md` + `SECURITY_RULES.md` + `DATABASE_RULES.md`).
> Governs the full pipeline: Document → Pages → Classification → Text/Table/Visual → Chunking → BGE embeddings → pgvector → Retrieval → Rerank → Evidence → LLM. The LLM never invents financial facts.

## 1. Pipeline Overview (Normative Order)

```
Document → Pages → Content classification (TEXT|TABLE|VISUAL)
 → Text processing / Table processing / Visual processing
 → Chunking (page-aware) → BGE embeddings (768-d, normalized)
 → PostgreSQL pgvector persist → Retrieval (tenant-filtered)
 → Optional reranking → Evidence context assembly
 → LLM (Groq, explain-only) → Answer + citations | insufficient_evidence
```

Skipping a stage (e.g., embedding without page metadata, retrieval without tenant filter) is a violation. Each stage's contract below MUST hold.

## 2. Ingestion Contracts

### 2.1 Document intake
- Accept: PDF only in v1 (other types → `422 unsupported_media_type` with safe message). Enforce MIME + magic-byte check, max size (e.g., 50 MB, tunable), page cap (e.g., 500, tunable).
- Compute `sha256`; dedupe per `(company_id, sha256)` → return existing document with `duplicate: true` instead of re-ingesting silently.
- Persist `documents` row with `status=pending` BEFORE heavy work; transitions: `pending → processing → ready | failed`. `failed` MUST set `error_code` (typed) + safe message.
- Only `analyst`+ may upload (see `SECURITY_RULES.md`); every upload emits an `audit_logs` row.

### 2.2 Pages
- Split PDF into `document_pages` preserving `page_number` (1-indexed, matching the PDF reader users see). Never renumber or merge pages.
- Record per-page `content_types` observed (subset of `TEXT,TABLE,VISUAL`) for diagnostics and eval.

### 2.3 Content classification
- Classify each page region/block into exactly one of: `TEXT` (prose/paragraphs), `TABLE` (grid/matrix with rows/cols), `VISUAL` (chart, infographic, image, scanned region with <50 extractable chars).
- Heuristic + parser signals (text density, ruling lines, image XObjects). Log classifier version per document for reproducibility.

### 2.4 Text processing
- Extract with a text-faithful parser; normalize whitespace/line-breaks; preserve headings/section hints where cheap (e.g., font-size cues → markdown `##`).
- Strip headers/footers/running page numbers ONLY when confidently repeated; never strip numbers inside tables or footnotes containing financial figures.
- Language: English-first in v1; non-English pages ingested as-is (no silent translation at ingest).

### 2.5 Table processing
- Extract cell structure (rows × cols, spanning cells flattened explicitly). Serialize each table to BOTH: (a) Markdown pipe table for LLM readability, (b) structured JSON (`headers[], rows[][]`) in `table_ref` for deterministic use.
- Preserve units/currency/footnote markers inline (e.g., `$m`, `%`, `*`) — never drop them.
- Never split a single logical table across two chunks if it fits the token budget; if oversized, split by row groups with repeated header row + `continued_from` marker.
- Tables containing financial figures MUST keep `page_number` + `bbox` so citations point at the source page.

### 2.6 Visual / infographic processing
- For charts/infographics/scanned regions: store image ref + generate a TEXT SURROGATE: (a) OCR numbers/labels, (b) structured caption (`chart_type, title, axes, legend, data_points[]` where extractable), (c) one-paragraph neutral description. Mark surrogate with `content_type=visual_caption` + `model/method` used.
- Surrogates MUST be labeled as machine-generated descriptions, never as verbatim management statements. Numbers from visuals are LOW-TRUST: usable as supporting context, never as sole source for an authoritative figure unless corroborated by text/table/SQL.
- Original image bytes/refs retained for frontend display alongside citations where licensing/storage allows.

## 3. Chunking Rules

1. Page-aware: every chunk belongs to exactly ONE page (`page_number` immutable). Cross-page merges forbidden.
2. Budgets (defaults, tunable at implementation): target ~400–600 tokens, hard cap ~800, overlap ~50–80 tokens for TEXT; TABLE chunks exempt from overlap but keep header repetition.
3. Boundaries: split on paragraph/section ends; never mid-sentence unless hard cap forces it (then mark `truncated: true`).
4. Metadata per chunk (mandatory): `company_id, document_id, page_id, page_number, chunk_index, content_type, token_count, embedding_model + revision`.
5. Deterministic: same document + same code version → byte-identical chunks (seeded, sorted). Chunking changes require version bump + re-embedding note.

## 4. Embedding Rules (BGE-base-en-v1.5, 768-d)

1. Model: `BAAI/bge-base-en-v1.5` via SentenceTransformers, pinned revision. No OpenAI/Groq embeddings swap without approval.
2. Normalize all vectors (L2) at write AND query time; store into `vector(768)` (see `DATABASE_RULES.md`).
3. Batch during ingest; single-vector path for queries. Never embed secrets; never send document text to Groq for embedding.
4. Record model id+revision per document; mixed-revision indexes forbidden.
5. Prefix convention (BGE best practice — finalize at implementation, e.g., passage/query prefixes) MUST be documented and applied consistently; changing it invalidates prior vectors.

## 5. Retrieval Rules

1. Tenant filter FIRST: `WHERE company_id = :cid` on every vector query. Global search forbidden.
2. Query embedding uses the same model+normalization+prefix as ingest.
3. Parameters: `top_k` default ~8 (tunable 4–12), distance cutoff (cosine) to drop weak hits, `MIN_SCORE` threshold below which hits are discarded even if `k` unfilled. Default similarity operator is cosine distance (`<=>` over L2-normalized BGE vectors); any change of operator/metric requires documenting score-direction semantics + re-tuning thresholds.
4. Return per hit: `chunk_id, document_id, page_number, content_type, text/table markdown, distance score`. Preserve ordering by score pre-rerank.
5. Filters allowed: `document_id[]`, `content_type[]`, page range, date range — all ANDed with tenant predicate. No filter may widen scope beyond tenant.
6. Empty/weak result → propagate `insufficient_evidence` signal upstream; do NOT pad with off-tenant or below-threshold chunks.

## 6. Reranking (Optional but Governed)

- Allowed: lightweight cross-encoder or LLM-free heuristic rerank (e.g., table-bonus for figure-seeking queries, recency/keyword overlap). Must be deterministic or seeded.
- Forbidden: reranker that invents text, drops citations, or filters by tenant-foreign signals.
- Must log `retrieved_k → reranked_k` + model id; A/B eval required before making rerank default (see `TESTING_RULES.md` retrieval tests).

## 7. Evidence Assembly & Budgets

1. `EvidenceAssembler` builds the ONLY context the LLM sees: `{ sql_rows?, calc_results?, chunks[{id, doc, page, type, text}] }` within a token budget (e.g., 4–6k tokens, tunable). Truncation drops lowest-score chunks first, never citations of kept chunks.
2. Every chunk in context MUST carry `{document_id, page_number, chunk_id}` through to the answer's `citations[]`.
3. SQL rows and calc results are labeled `VERIFIED_STRUCTURED` / `VERIFIED_CALCULATION`; RAG chunks labeled `DOCUMENT_EVIDENCE (trust: high|low)` with visuals marked `low` per §2.6.
4. If post-assembly evidence cannot support the question (no rows AND no above-threshold chunks AND no calc inputs), set `status=insufficient_evidence` and skip-or-constrain the LLM call (LLM may only phrase the insufficiency + suggest what to upload/provide).

## 8. Generation Rules (Groq LLM — Explain Only)

1. System prompt MUST contain, verbatim in intent: "You are a finance explainer, not a calculator or source. Use ONLY the provided evidence. Never invent numbers, dates, quotes, or citations. If evidence is insufficient, say so explicitly. Cite every financial fact as [doc:page:chunk]. Do not perform arithmetic — quote the VERIFIED_CALCULATION block."
2. Temperature low (e.g., 0–0.2); max tokens bounded; stop on citation-format violation where enforceable via post-check.
3. Post-generation verification (code, not LLM): every `[doc:page:chunk]` cited MUST exist in the evidence set; every number in `VERIFIED_*` blocks quoted exactly (string match after normalization) OR the answer is rejected → fallback to `insufficient_evidence` + log `citation_verification_failed`.
4. LLM MUST NOT output: new financial figures, page numbers not in evidence, document titles not in evidence, or arithmetic derivations. Explanatory prose without new facts is allowed.
5. On `LLMUnavailable` (timeout/5xx/rate-limit): return typed `llm_unavailable` error with retry guidance — never a fabricated answer.

## 9. Citation Contract (User-Visible)

- Every answer stating a financial fact MUST include `citations: [{document_id, page_number, chunk_id, snippet?}]` minimum. Snippets ≤ ~300 chars, verbatim.
- Frontend renders each citation as `DocumentTitle — p.N` with hover/expand snippet; clicking opens document at page (where viewer available).
- `insufficient_evidence` responses MUST include: `missing: [...]` (e.g., `["revenue.2024", "management guidance chunk"]`), `suggestions: [...]` (upload X, narrow period), and `route` + `confidence` for transparency.

## 10. Forbidden Behaviors (RAG-Specific)

- Hallucinating facts, quotes, pages, or tables.
- Quoting visual surrogates as verbatim management text.
- Mixing tenants' chunks in one answer.
- Using LLM arithmetic as authority (see calculation rule).
- Returning un-cited financial claims "for demo smoothness".
- Logging/storing full prompts with PII at info level.

## 11. Observability for RAG

- Log per Q&A: `route, confidence, retrieved_k, kept_k, reranked?, evidence_tokens, llm_latency_ms, citation_check: pass|fail`.
- Persist `ai_messages.evidence_refs + citations + route` for eval and audit. Evaluations (retrieval recall@k, routing accuracy, citation precision) defined in `TESTING_RULES.md`.

## 12. Phase 5 Implementation Notes (Normative for Built Behavior)

What Phase 5 actually built (retrieval foundation; generation/router are later):

1. **Status reconciliation**: `documents.status` (`uploaded|processing|indexed|failed`) means pages-ready at `indexed`. Vector readiness is the separate `documents.embedding_status` (`pending|indexing|ready|failed`). Only `ready` is retrievable. The `pending|ready` vocabulary in §2.1 above is superseded for documents by this section; §2.1 still governs future chunk-pipeline wording.
2. **Chunking (actual)**: single-page chunks only (§3.1); hierarchy page → paragraph → sentence → hard word-boundary split; char budgets `RAG_CHUNK_SIZE=2000` / `RAG_CHUNK_OVERLAP=256` (~500/~64 tokens at ~4 chars/token); overlap trails the previous chunk cut at a word boundary; `<50`-char and visual-only pages skipped deterministically; table pages kept whole while fitting with `chunk_type=table`; `token_count` stored as `chars//4` ESTIMATE (chunker is model-free by design).
3. **BGE prefix convention (exact)**: queries are prefixed with `Represent this sentence for searching relevant passages: `; documents carry NO prefix. Same text in different roles embeds differently, by design. Changing this invalidates all stored vectors (re-embed required).
4. **Normalization + metric**: L2-normalized on both sides (`normalize_embeddings=True`); retrieval uses pgvector cosine distance (`<=>`, lower is better); API presents `score = 1 - distance` (higher is better). Never call a distance a similarity.
5. **Threshold semantics**: `RAG_SIMILARITY_THRESHOLD` is a MINIMUM SIMILARITY in [0,1], default `0.0` (no filtering). Baseline default, NOT calibrated — tune against evaluation data before raising.
6. **Top-K behavior**: `RAG_TOP_K=8` default, `RAG_MAX_TOP_K=20` ceiling (over-max rejected with 422, never silently clamped); ordering is distance then chunk id (deterministic ties).
7. **Tenant filtering**: `WHERE company_id = :cid` inside the vector SQL on every search, plus allowlisted `document_id` / `fiscal_year` / `page_number` filters. Global-then-Python-filter is forbidden and untested paths assert zero cross-tenant hits.
8. **Index**: HNSW + `vector_cosine_ops`, default build params, declared in model metadata (drift-free `alembic check`).
9. **Model/version handling**: every chunk stores `embedding_model` (`BAAI/bge-base-en-v1.5`) + `embedding_dimensions` (768, CHECK-enforced); re-index is delete/rebuild per document (idempotent, no stale chunks); model loads once per process (singleton + lock), batch encode only.
