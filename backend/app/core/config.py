"""Application configuration.

Single source of truth for environment-driven settings (Pydantic Settings).
Env-only: no hardcoded secrets, no defaults for required values.
See DEVELOPMENT_RULES.md §8, SECURITY_RULES.md §1.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend settings. Fails fast on missing/invalid required values."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "finance-dashboard"
    app_env: Literal["local", "dev", "staging", "prod"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Required: no default on purpose. Same scheme works for Supabase
    # PostgreSQL later (only the URL value changes, never this code).
    database_url: PostgresDsn

    # --- Phase 2: JWT authentication (all from env, never hard-coded) ---
    # HS256 chosen per SECURITY_RULES.md §2 (RS256 deferred to a later phase).
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, gt=0)

    # --- Phase 4: document ingestion (all tunable, no secrets here) ---
    # Filesystem root for LocalFileStorage. Override per environment; tests
    # point it at tmp_path. A future S3/Supabase backend needs no code change
    # in callers (StorageService interface), only a new implementation.
    document_storage_root: str = "./storage/documents"
    document_max_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    document_max_pages: int = Field(default=200, gt=0)

    # --- Phase 5: retrieval foundation (documented defaults, all tunable) ---
    # Char budgets approximate BGE tokens at ~4 chars/token: 2000 ≈ 500
    # tokens (RAG_RULES §3 target 400–600), overlap 256 ≈ 64 (range 50–80).
    embedding_model_name: str = Field(default="BAAI/bge-base-en-v1.5", min_length=1)
    embedding_dimensions: int = Field(default=768, gt=0)
    embedding_batch_size: int = Field(default=32, gt=0)
    rag_chunk_size: int = Field(default=2000, ge=200)
    rag_chunk_overlap: int = Field(default=256, ge=0)
    rag_top_k: int = Field(default=8, gt=0)
    rag_max_top_k: int = Field(default=20, gt=0)
    # Minimum cosine SIMILARITY (1 - distance) to keep a hit. 0.0 = no
    # filtering. Baseline default, NOT calibrated: tune with eval data later.
    rag_similarity_threshold: float = Field(default=0.0, ge=0.0, le=1.0)

    # --- Phase 7: Groq answer generation (all tunable; key optional) ---
    # groq_api_key is None-able ON PURPOSE: the app must import and serve
    # everything else without a key; /ai/answer fails closed (503) instead.
    groq_api_key: str | None = Field(default=None, min_length=1)
    groq_model: str = Field(default="llama-3.3-70b-versatile", min_length=1)
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1")
    groq_timeout_seconds: float = Field(default=30.0, gt=0)
    groq_max_output_tokens: int = Field(default=1024, gt=0)
    groq_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    ai_max_evidence_items: int = Field(default=10, gt=0)
    ai_max_evidence_chars: int = Field(default=2000, gt=0)

    # --- Phase 9: conversation context window (supporting context only) ---
    # Bounded recent history sent to the LLM; oldest trimmed first. History
    # is NEVER authoritative evidence regardless of these budgets.
    ai_max_conversation_messages: int = Field(default=10, gt=0)
    ai_max_conversation_chars: int = Field(default=12000, gt=0)

    # --- Phase 11: production deployment (all optional, safe defaults) ---
    # CORS_ORIGINS: explicit frontend origin(s) for cross-origin production
    # deployments (e.g. "https://app.example.com,https://admin.example.com").
    # Empty (default) = no CORS middleware; the local same-origin Next.js
    # rewrite proxy needs none. A wildcard "*" is REJECTED at startup because
    # the API uses credentialed Bearer auth (SECURITY_RULES.md §5).
    cors_origins: list[str] = Field(default_factory=list)
    # Managed-PostgreSQL pool tuning. Defaults match the historic engine
    # behavior; override per environment for Supabase direct/pooler URLs.
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_pool_max_overflow: int = Field(default=10, ge=0, le=100)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                import json as _json

                try:
                    parsed = _json.loads(text)
                except ValueError:
                    parsed = text
                if isinstance(parsed, list):
                    return [str(o).strip() for o in parsed if str(o).strip()]
                return []
            return [o.strip() for o in text.split(",") if o.strip()]
        return value

    @model_validator(mode="after")
    def _check_cors_safety(self) -> "Settings":
        if any(o == "*" for o in self.cors_origins):
            raise ValueError('cors_origins must be explicit origins; "*" is forbidden.')
        return self

    @model_validator(mode="after")
    def _check_rag_consistency(self) -> "Settings":
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("rag_chunk_overlap must be smaller than rag_chunk_size.")
        if self.rag_max_top_k < self.rag_top_k:
            raise ValueError("rag_max_top_k must be >= rag_top_k.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance. Callers must never mutate the result."""
    return Settings()
