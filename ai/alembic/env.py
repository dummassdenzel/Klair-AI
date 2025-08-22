from logging.config import fileConfig
import sys
import os

from sqlalchemy import engine_from_config, pool
from alembic import context

# --- Alembic Config object ---
config = context.config

# --- Logging setup ---
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Add project root to sys.path ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Import your settings + Base ---
from config import settings
from database.database import Base
from database import models

# --- Set metadata for autogenerate ---
target_metadata = Base.metadata

# --- Convert async URL to sync URL for Alembic ---
sync_database_url = settings.DATABASE_URL
if sync_database_url.startswith('postgresql+asyncpg://'):
    sync_database_url = sync_database_url.replace('postgresql+asyncpg://', 'postgresql://')

config.set_main_option("sqlalchemy.url", sync_database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
