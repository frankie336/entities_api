import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- PATH FIX (Keep this) ---
project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# --- MODELS IMPORT (Keep this) ---
from src.api.entities_api.models.models import Base

# This is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the target metadata for 'autogenerate' support
target_metadata = Base.metadata

#------------------------------------------------------------------------------------
# Uncomment DB_URL="mysql+pymysql... and comment DB_URL = os.getenv("DATABASE_URL")
# when deploying model upgrades
#------------------------------------------------------------------------------------
DB_URL = os.getenv("DATABASE_URL")
# DB_URL="mysql+pymysql://api_user:ee7d06c5bb265caed9b9d942d210d84d91be511138e498b5682e3a1f463c5539@localhost:3307/entities_db"

if not DB_URL:
    raise ValueError("FATAL: DATABASE_URL environment variable is not set or empty.")

# Manually set the 'sqlalchemy.url' in the config object that Alembic uses.
# This will override anything in alembic.ini.
config.set_main_option("sqlalchemy.url", DB_URL)
# --- END OF NEW SECTION ---


def run_migrations_offline() -> None:
    # ... (This function remains the same) ...
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
    # ... (This function is now simpler and more reliable) ...
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
