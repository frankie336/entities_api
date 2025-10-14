# safe_ddl.py – helpers for idempotent Alembic operations
# Place this inside migrations/utils/ or another importable location

from typing import Any, Optional

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

__all__ = [
    "has_table",
    "has_column",
    "column_exists",
    "add_column_if_missing",
    "drop_column_if_exists",
    "safe_alter_column",
    "rename_column_if_exists",
    "safe_execute_sql",
]

# ─────────────────────────────────────────────────────────────────────────────
# Core inspection helpers
# ─────────────────────────────────────────────────────────────────────────────


def has_table(table_name: str) -> bool:
    """Check if a table exists in the current bind."""
    bind = op.get_bind()
    insp = inspect(bind)
    return insp.has_table(table_name)


def has_column(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    insp = inspect(bind)
    if not insp.has_table(table_name):
        return False
    return column_name in {col["name"] for col in insp.get_columns(table_name)}


# Some scripts import 'column_exists'; keep it as an alias for compatibility.
column_exists = has_column

# ─────────────────────────────────────────────────────────────────────────────
# Column-level operations
# ─────────────────────────────────────────────────────────────────────────────


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    """Add a column only if the table exists and the column is missing."""
    if not has_table(table_name):
        _log(f"⚠️ Skipped add column – table not found: {table_name}")
        return

    if not has_column(table_name, column.name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(column)
        _log(f"✅ Added column: {table_name}.{column.name}")
    else:
        _log(
            f"⚠️ Skipped add column – column already exists: {table_name}.{column.name}"
        )


def drop_column_if_exists(table_name: str, column_name: str) -> None:
    """Drop a column only if both the table and column exist."""
    if not has_table(table_name):
        _log(f"⚠️ Skipped drop column – table not found: {table_name}")
        return

    if has_column(table_name, column_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column(column_name)
        _log(f"🗑️ Dropped column: {table_name}.{column_name}")
    else:
        _log(
            f"⚠️ Skipped drop column – column already absent: {table_name}.{column_name}"
        )


def safe_alter_column(table_name: str, column_name: str, **kwargs: Any) -> None:
    """
    Alter a column only if both the table and column exist.
    kwargs are passed directly to batch_op.alter_column (e.g., nullable=..., type_=..., existing_type=...).
    """
    if not has_table(table_name):
        _log(f"⚠️ Skipped alter column – table not found: {table_name}")
        return

    if has_column(table_name, column_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(column_name, **kwargs)
        _log(f"✏️ Altered column: {table_name}.{column_name}")
    else:
        _log(f"⚠️ Skipped alter column – column not found: {table_name}.{column_name}")


def rename_column_if_exists(
    table_name: str,
    old_name: str,
    new_name: str,
    *,
    existing_type: Optional[sa.types.TypeEngine] = None,
    existing_nullable: Optional[bool] = None,
) -> None:
    """
    Rename a column (old_name -> new_name) only if table exists, old exists, and new doesn't.
    MySQL/MariaDB require existing_type/existing_nullable for ALTER in some cases; pass them if known.
    """
    if not has_table(table_name):
        _log(f"⚠️ Skipped rename – table not found: {table_name}")
        return

    if not has_column(table_name, old_name):
        _log(f"⚠️ Skipped rename – source column not found: {table_name}.{old_name}")
        return

    if has_column(table_name, new_name):
        _log(f"⚠️ Skipped rename – target already exists: {table_name}.{new_name}")
        return

    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            old_name,
            new_column_name=new_name,
            existing_type=existing_type,
            existing_nullable=existing_nullable,
        )
    _log(f"🔤 Renamed column: {table_name}.{old_name} → {new_name}")


# ─────────────────────────────────────────────────────────────────────────────
# Misc
# ─────────────────────────────────────────────────────────────────────────────


def safe_execute_sql(sql: str) -> None:
    """
    Execute raw SQL and print a short log. Use for guarded UPDATE backfills, etc.
    Caller is responsible for table/column checks.
    """
    bind = op.get_bind()
    _log(f"🛠️ Executing SQL: {sql}")
    bind.exec_driver_sql(sql)


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────


def _log(msg: str) -> None:
    print(f"[alembic.safe_ddl] {msg}", flush=True)
