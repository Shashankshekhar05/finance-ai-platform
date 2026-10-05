"""Alembic environment. URL comes from Settings, never from alembic.ini.

`target_metadata` is Base.metadata (health-only in Phase 1, identity tables
in Phase 2). No `create_all`, no seed data, no business logic here.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure `app.*` is importable when alembic runs from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402

# Phase 2 models register on Base.metadata via these imports.
import app.models.company  # noqa: E402,F401
import app.models.user  # noqa: E402,F401
import app.models.user_role  # noqa: E402,F401

# Phase 3 finance models.
import app.models.expense  # noqa: E402,F401
import app.models.financial_metric  # noqa: E402,F401
import app.models.revenue  # noqa: E402,F401
import app.models.transaction  # noqa: E402,F401

# Phase 4 document models.
import app.models.document  # noqa: E402,F401
import app.models.document_page  # noqa: E402,F401

# Phase 5 chunk model.
import app.models.document_chunk  # noqa: E402,F401

# Phase 9 conversation models.
import app.models.conversation  # noqa: E402,F401
import app.models.conversation_message  # noqa: E402,F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL is the single connection source (local now, Supabase later).
config.set_main_option("sqlalchemy.url", str(get_settings().database_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
