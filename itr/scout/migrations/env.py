"""Alembic environment — wired to scout.config.settings.database_url.

No connection string lives in alembic.ini; it's read from the same
Settings object every other module in this project uses, so .env.local
stays the single source of truth.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from scout.canonical.models import Base
from scout.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    """Restrict autogenerate to the itr360 schema only.

    This Postgres instance also hosts unrelated schemas from a
    different subsystem (src_slack / src_workday / src_zendesk).
    Without this filter, autogenerate compares the ENTIRE database
    against our itr360-only metadata and proposes dropping every
    table it doesn't manage — not something this migration should
    ever touch.
    """
    if type_ == "schema":
        return name == "itr360"
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
