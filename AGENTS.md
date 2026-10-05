# Finance Dashboard — Project Constitution

## 1. Mission

Build a production-grade AI Finance Dashboard.

This is not a toy chatbot or CRUD demo.

The system must support:

- Financial data analytics
- Financial document ingestion
- PDF text extraction
- Table extraction
- Visual/image understanding
- RAG
- SQL analytics
- Deterministic financial calculations
- Hybrid SQL + RAG reasoning
- Source-aware answers
- Authentication and authorization
- Multi-user/company isolation

---

## 2. Architecture Authority

The following documents are part of the project architecture:

- ARCHITECTURE.md
- DEVELOPMENT_RULES.md
- DATABASE_RULES.md
- RAG_RULES.md
- SECURITY_RULES.md
- TESTING_RULES.md

Read the relevant document before implementing work in that domain.

If an implementation decision conflicts with these documents, do not silently override them.

Stop and explain the conflict before making an architectural change.

---

## 3. Technology Baseline

### Backend

- Python
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- Alembic

### Database

- PostgreSQL
- pgvector

### Frontend

- Next.js
- TypeScript
- Tailwind CSS

### AI

- Groq for LLM inference
- SentenceTransformers
- BAAI/bge-base-en-v1.5 for embeddings
- 768-dimensional embeddings

---

## 4. Core Engineering Principle

The coding agent is an IMPLEMENTER, not the ARCHITECT.

Do not silently:

- replace PostgreSQL
- replace FastAPI
- replace Next.js
- replace Groq
- replace BGE embeddings
- introduce another vector database
- introduce another ORM
- move backend logic into frontend
- expose secrets to frontend
- change authentication architecture

If a change is genuinely required:

1. Stop.
2. Explain why.
3. Explain alternatives.
4. Explain trade-offs.
5. Explain migration impact.
6. Wait for approval.

---

## 5. Think Before Coding

Before modifying code:

1. Understand the request.
2. Inspect relevant existing code.
3. Read relevant architecture/rule files.
4. Identify assumptions.
5. Identify risks.
6. Define a small implementation plan.
7. Define how success will be verified.

Do not guess when an important requirement is ambiguous.

---

## 6. Simplicity First

Prefer the simplest production-appropriate solution.

Do not introduce:

- speculative abstractions
- unnecessary configuration
- unnecessary dependencies
- premature optimization
- duplicate systems
- features that were not requested

Every architectural component must have a reason to exist.

---

## 7. Backend Boundary

Backend owns:

- business logic
- authentication
- authorization
- database access
- financial calculations
- RAG retrieval
- LLM orchestration
- document processing

Frontend must never become the source of truth for these responsibilities.

---

## 8. Financial Calculation Rule

The LLM is never the authoritative calculator.

Financial calculations must be performed by deterministic backend code.

The LLM may explain verified results but must not invent or independently calculate authoritative financial figures.

---

## 9. AI Grounding Rule

AI responses must be grounded in verified evidence.

Never invent:

- financial numbers
- dates
- percentages
- document statements
- sources

If sufficient evidence is unavailable, explicitly return an insufficient-evidence response.

---

## 10. Security Rule

Never expose secrets in frontend code.

Never commit:

- API keys
- database passwords
- JWT secrets
- service credentials

Use environment variables.

Never commit `.env`.

---

## 11. Database Rule

Database schema changes must use Alembic migrations.

Do not rely on application startup to create production tables.

Tenant/company isolation must be enforced in backend database access.

---

## 12. Testing Rule

A feature is not complete merely because it runs.

Relevant tests must be created or updated.

At minimum, critical functionality must have automated verification.

---

## 13. Change Discipline

Make surgical changes.

Do not refactor unrelated code.

Do not modify files unrelated to the requested task unless required.

Remove only dead code introduced by your own changes.

---

## 14. Verification

After implementation:

- run relevant tests
- run type checks where applicable
- run linting where configured
- verify the actual behavior
- report failures honestly

Never claim a task is complete without verification.

---

## 15. Completion Report

Every implementation task must end with:

### Changed
List changed files and important changes.

### Tests
List tests/commands executed.

### Validation
Explain what was verified.

### Remaining
List known limitations or follow-up work.

---

## 16. Architecture Evolution

Architecture may evolve as the project grows.

However, architectural changes must be deliberate, documented, and backwards-conscious.

Do not optimize for novelty.

Optimize for:

- correctness
- maintainability
- security
- observability
- testability
- production readiness