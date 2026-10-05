"""Phase 11 deployment-readiness tests: Supabase target, no live Supabase needed.

Covers the production-deploy contract WITHOUT touching a real Supabase
project: connection-URL compatibility, pool tuning, CORS safety, Alembic
chain integrity, pgvector metadata, health-envelope safety, storage
boundaries, and secret hygiene. Live-database behavior (tenant isolation,
calculations, retrieval, AI) is covered by the existing suites against a
production-like local PostgreSQL + pgvector.
"""

from pathlib import Path

import pytest
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import LargeBinary

import app.models  # noqa: F401 — register all ORM mappers
from app.core.config import Settings
from app.db.base import Base
from app.db.engine import create_engine_for
from app.models.document_chunk import DocumentChunk

_DEV_JWT = "test-only-secret-that-is-long-enough-123456"
_LOCAL_URL = "postgresql+psycopg2://u:p@localhost:5432/db"
# Shape of a Supabase pooled connection string (direct uses port 5432).
_SUPABASE_POOLER_URL = (
    "postgresql://postgres:EXAMPLE_PASSWORD@db.abcd1234.supabase.co:6543/postgres"
    "?sslmode=require"
)
_SUPABASE_DIRECT_URL = (
    "postgresql://postgres:EXAMPLE_PASSWORD@db.abcd1234.supabase.co:5432/postgres"
    "?sslmode=require"
)


def _settings(**kwargs) -> Settings:
    base: dict = {
        "_env_file": None,
        "database_url": _LOCAL_URL,
        "jwt_secret_key": _DEV_JWT,
    }
    base.update(kwargs)
    return Settings(**base)


# --- 1. Production-like DATABASE_URL configuration -------------------------


def test_supabase_pooler_url_accepted() -> None:
    settings = _settings(database_url=_SUPABASE_POOLER_URL)
    assert str(settings.database_url).startswith("postgresql://")
    assert "sslmode=require" in str(settings.database_url)


def test_supabase_direct_url_accepted() -> None:
    settings = _settings(database_url=_SUPABASE_DIRECT_URL)
    assert ":5432" in str(settings.database_url)


def test_engine_builds_for_supabase_url_without_connecting() -> None:
    # create_engine is lazy: no TCP connection is opened here.
    engine = create_engine_for(_SUPABASE_POOLER_URL)
    try:
        assert engine.url.drivername == "postgresql"
        # QueuePool.status() reports the configured pool size.
        assert "Pool size: 5" in engine.pool.status()
    finally:
        engine.dispose()


def test_engine_pool_defaults_preserve_historic_behavior() -> None:
    engine = create_engine_for(_LOCAL_URL)
    try:
        assert "Pool size: 5" in engine.pool.status()  # pool_size=5, overflow=10
    finally:
        engine.dispose()


def test_engine_pool_tunable_per_environment() -> None:
    engine = create_engine_for(_SUPABASE_POOLER_URL, pool_size=2, max_overflow=3)
    try:
        assert "Pool size: 2" in engine.pool.status()
    finally:
        engine.dispose()


def test_pool_settings_from_environment() -> None:
    settings = _settings(db_pool_size=3, db_pool_max_overflow=7)
    assert settings.db_pool_size == 3
    assert settings.db_pool_max_overflow == 7


def test_app_boots_without_groq_key() -> None:
    # Groq is optional at startup; /ai/* fails closed (503) instead.
    assert _settings(groq_api_key=None).groq_api_key is None


def test_prod_app_env_accepted() -> None:
    assert _settings(app_env="prod").app_env == "prod"


# --- 2. CORS: explicit origins only ----------------------------------------


def test_cors_defaults_to_disabled() -> None:
    assert _settings().cors_origins == []


def test_cors_parses_comma_separated_env() -> None:
    settings = _settings(cors_origins="https://app.example.com, https://b.example.com")
    assert settings.cors_origins == ["https://app.example.com", "https://b.example.com"]


def test_cors_parses_json_list_env() -> None:
    settings = _settings(cors_origins='["https://app.example.com"]')
    assert settings.cors_origins == ["https://app.example.com"]


def test_cors_rejects_wildcard() -> None:
    with pytest.raises(ValidationError):
        _settings(cors_origins="*")
    with pytest.raises(ValidationError):
        _settings(cors_origins="https://app.example.com,*")


def _app_with_cors(monkeypatch: pytest.MonkeyPatch, origins: object):  # type: ignore[no-untyped-def]
    import app.main as main_module

    settings = _settings(cors_origins=origins)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    return main_module.create_app()


def test_no_cors_middleware_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    monkeypatch.setattr(main_module, "get_settings", _settings)
    app = main_module.create_app()
    assert not any(m.cls is CORSMiddleware for m in app.user_middleware)


def test_cors_middleware_uses_explicit_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_with_cors(monkeypatch, "https://app.example.com")
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_origins"] == ["https://app.example.com"]
    assert cors[0].kwargs["allow_credentials"] is True
    assert cors[0].kwargs["allow_origins"] != ["*"]


# --- 3. Alembic chain: single head, upgrade+downgrade everywhere ------------


def _script_directory():  # type: ignore[no-untyped-def]
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config()
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    return ScriptDirectory.from_config(config)


def test_alembic_single_head() -> None:
    assert len(_script_directory().get_heads()) == 1


def test_alembic_chain_is_linear_from_head_to_base() -> None:
    script = _script_directory()
    (head,) = script.get_heads()
    reachable: set[str] = set()
    revision: str | None = head
    while revision is not None:
        reachable.add(revision)
        down = script.get_revision(revision).down_revision
        revision = down if isinstance(down, str) else (down[0] if down else None)
    total = {rev.revision for rev in script.walk_revisions()}
    assert reachable == total


def test_alembic_every_revision_has_upgrade_and_downgrade() -> None:
    for rev in _script_directory().walk_revisions():
        assert callable(rev.module.upgrade), rev.revision
        assert callable(rev.module.downgrade), rev.revision


def test_alembic_env_reads_database_url_from_settings() -> None:
    env_py = Path(__file__).resolve().parents[1] / "alembic" / "env.py"
    content = env_py.read_text(encoding="utf-8")
    assert "get_settings" in content
    assert "metadata.create_all" not in content  # comment mentions are fine
    assert "upgrade head" not in content  # migrations run via the CLI job


def test_pgvector_foundation_migration_uses_if_not_exists() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0001_enable_pgvector.py"
    )
    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration.read_text(
        encoding="utf-8"
    )


# --- 4. pgvector metadata: vector(768) + HNSW cosine ------------------------


def test_chunk_embedding_is_vector_768() -> None:
    column_type = DocumentChunk.__table__.c.embedding.type
    dimensions = getattr(column_type, "dim", getattr(column_type, "dimensions", None))
    assert dimensions == 768
    assert DocumentChunk.__table__.c.embedding.nullable is False


def test_chunk_hnsw_cosine_index_declared() -> None:
    index = next(
        i
        for i in DocumentChunk.__table__.indexes
        if i.name == "ix_chunks_embedding_hnsw"
    )
    options = index.dialect_options.get("postgresql", {})
    assert options.get("using") == "hnsw"
    assert options.get("ops") == {"embedding": "vector_cosine_ops"}


# --- 5. Health envelopes carry no infrastructure secrets --------------------


@pytest.fixture()
def live_client():  # type: ignore[no-untyped-def]
    """App client, skipped when required env settings are absent."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    try:
        return TestClient(create_app())
    except ValidationError:
        pytest.skip("backend settings not configured in this environment")


def test_liveness_shape_has_no_secret_surface(live_client) -> None:  # type: ignore[no-untyped-def]
    response = live_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_envelope_leaks_nothing(live_client) -> None:  # type: ignore[no-untyped-def]
    response = live_client.get("/no-such-route-anywhere")
    assert response.status_code == 404
    body = response.json()["error"]
    assert set(body) == {"code", "message", "details", "request_id"}
    assert "traceback" not in response.text.lower()


# --- 6. Storage boundary: no binary columns, env-rooted local backend -------


def test_no_binary_columns_in_postgres_schema() -> None:
    binary = [
        f"{table}.{column.name}"
        for table, columns in (
            (name, table.columns) for name, table in Base.metadata.tables.items()
        )
        for column in columns
        if isinstance(column.type, LargeBinary)
    ]
    assert binary == []


def test_storage_root_is_environment_configurable(tmp_path: Path) -> None:
    settings = _settings(document_storage_root=str(tmp_path))
    assert settings.document_storage_root == str(tmp_path)


def test_local_storage_rejects_traversal(tmp_path: Path) -> None:
    from app.services.storage import LocalFileStorage

    storage = LocalFileStorage(root=tmp_path)
    with pytest.raises(ValueError):
        storage.put(key="../escape.pdf", data=b"x")
    with pytest.raises(ValueError):
        storage.put(key="/absolute.pdf", data=b"x")


# --- 7. Secret/config hygiene -----------------------------------------------


def test_env_example_has_placeholders_only() -> None:
    content = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )
    assert "gsk_" not in content
    assert "CHANGE_ME" in content  # JWT placeholder, never a real secret
    assert "CORS_ORIGINS" in content
    assert "DB_POOL_SIZE" in content
    assert "DB_POOL_MAX_OVERFLOW" in content
    assert "supabase.co" not in content  # no real project references


def test_settings_never_ship_a_default_jwt_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=_LOCAL_URL)
