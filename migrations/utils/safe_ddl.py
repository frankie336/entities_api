# safe_ddl.py – helpers for idempotent Alembic operations
# Place this inside migrations/utils/ or another importable location

from typing import Any, List, Optional

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
    # Index helpers
    "create_index_if_missing",
    "drop_index_if_exists",
    # FK helpers
    "has_fk",
    "drop_fk_if_exists",
    "create_fk_if_not_exists",
    "replace_fk",
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
# Index-level operations
# ─────────────────────────────────────────────────────────────────────────────


def create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: List[str],
    **kwargs: Any,
) -> None:
    """
    Create an index only if the table exists and the index is not already present.
    Safe to call on a fresh database where the table may not yet exist.
    kwargs are passed directly to op.create_index (e.g., unique=True).
    """
    if not has_table(table_name):
        _log(f"⚠️  Skipped create index – table not found: {table_name}")
        return

    bind = op.get_bind()
    insp = inspect(bind)
    existing = {idx["name"] for idx in insp.get_indexes(table_name)}

    if index_name not in existing:
        op.create_index(index_name, table_name, columns, **kwargs)
        _log(f"✅  Created index: {index_name} on {table_name}({', '.join(columns)})")
    else:
        _log(f"⚠️  Skipped create index – already exists: {index_name}")


def drop_index_if_exists(index_name: str, table_name: str) -> None:
    """
    Drop an index only if both the table and the index currently exist.
    Safe to call during downgrade on a schema that may already be partially
    rolled back.
    """
    if not has_table(table_name):
        _log(f"⚠️  Skipped drop index – table not found: {table_name}")
        return

    bind = op.get_bind()
    insp = inspect(bind)
    existing = {idx["name"] for idx in insp.get_indexes(table_name)}

    if index_name in existing:
        op.drop_index(index_name, table_name=table_name)
        _log(f"🗑️  Dropped index: {index_name} from {table_name}")
    else:
        _log(f"⚠️  Skipped drop index – not found: {index_name}")


# ─────────────────────────────────────────────────────────────────────────────
# FK inspection helpers
# ─────────────────────────────────────────────────────────────────────────────


def has_fk(table_name: str, constraint_name: str) -> bool:
    """
    Return True if a foreign-key constraint with the given name exists on the table.

    Uses information_schema so constraint names are authoritative (not inferred
    from SQLAlchemy metadata, which may differ from what MySQL actually stored).
    """
    if not has_table(table_name):
        return False
    bind = op.get_bind()
    insp = inspect(bind)
    fks = insp.get_foreign_keys(table_name)
    return any(fk.get("name") == constraint_name for fk in fks)


def drop_fk_if_exists(table_name: str, constraint_name: str) -> None:
    """
    Drop a foreign-key constraint by name only if it currently exists.
    Safe to call on a table that has already been migrated.
    """
    if not has_table(table_name):
        _log(f"⚠️  Skipped drop FK – table not found: {table_name}")
        return

    if has_fk(table_name, constraint_name):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")
        _log(f"🗑️  Dropped FK: {table_name}.{constraint_name}")
    else:
        _log(f"⚠️  Skipped drop FK – constraint not found: {table_name}.{constraint_name}")


def create_fk_if_not_exists(
    constraint_name: str,
    source_table: str,
    referent_table: str,
    local_cols: List[str],
    remote_cols: List[str],
    *,
    ondelete: Optional[str] = None,
    onupdate: Optional[str] = None,
) -> None:
    """
    Create a foreign-key constraint only if it does not already exist.
    Safe to call on a table that has already been migrated.
    """
    if not has_table(source_table):
        _log(f"⚠️  Skipped create FK – source table not found: {source_table}")
        return

    if has_fk(source_table, constraint_name):
        _log(
            f"⚠️  Skipped create FK – constraint already exists: "
            f"{source_table}.{constraint_name}"
        )
        return

    op.create_foreign_key(
        constraint_name,
        source_table,
        referent_table,
        local_cols,
        remote_cols,
        ondelete=ondelete,
        onupdate=onupdate,
    )
    rule = f" ON DELETE {ondelete}" if ondelete else ""
    _log(f"✅  Created FK: {source_table}.{constraint_name} → {referent_table}{rule}")


def replace_fk(
    constraint_name: str,
    source_table: str,
    referent_table: str,
    local_cols: List[str],
    remote_cols: List[str],
    *,
    ondelete: Optional[str] = None,
    onupdate: Optional[str] = None,
) -> None:
    """
    Atomically drop-and-recreate a FK constraint with new delete/update rules.

    This is the canonical helper for FK migrations:
      - Drops only if the constraint currently exists (idempotent on upgrade).
      - Creates only if it does not yet exist (idempotent on re-run).

    Usage:
        replace_fk(
            "files_ibfk_1",
            "files", "users",
            ["user_id"], ["id"],
            ondelete="CASCADE",
        )
    """
    drop_fk_if_exists(source_table, constraint_name)
    create_fk_if_not_exists(
        constraint_name,
        source_table,
        referent_table,
        local_cols,
        remote_cols,
        ondelete=ondelete,
        onupdate=onupdate,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Column-level operations
# ─────────────────────────────────────────────────────────────────────────────


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    """Add a column only if the table exists and the column is missing."""
    if not has_table(table_name):
        _log(f"⚠️  Skipped add column – table not found: {table_name}")
        return

    if not has_column(table_name, column.name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(column)
        _log(f"✅  Added column: {table_name}.{column.name}")
    else:
        _log(f"⚠️  Skipped add column – column already exists: {table_name}.{column.name}")


def drop_column_if_exists(table_name: str, column_name: str) -> None:
    """Drop a column only if both the table and column exist."""
    if not has_table(table_name):
        _log(f"⚠️  Skipped drop column – table not found: {table_name}")
        return

    if has_column(table_name, column_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column(column_name)
        _log(f"🗑️  Dropped column: {table_name}.{column_name}")
    else:
        _log(f"⚠️  Skipped drop column – column already absent: {table_name}.{column_name}")


def safe_alter_column(table_name: str, column_name: str, **kwargs: Any) -> None:
    """
    Alter a column only if both the table and column exist.
    kwargs are passed directly to batch_op.alter_column
    (e.g., nullable=..., type_=..., existing_type=...).
    """
    if not has_table(table_name):
        _log(f"⚠️  Skipped alter column – table not found: {table_name}")
        return

    if has_column(table_name, column_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(column_name, **kwargs)
        _log(f"✏️  Altered column: {table_name}.{column_name}")
    else:
        _log(f"⚠️  Skipped alter column – column not found: {table_name}.{column_name}")


def rename_column_if_exists(
    table_name: str,
    old_name: str,
    new_name: str,
    *,
    existing_type: Optional[sa.types.TypeEngine] = None,
    existing_nullable: Optional[bool] = None,
) -> None:
    """
    Rename a column (old_name -> new_name) only if table exists,
    old exists, and new doesn't.
    """
    if not has_table(table_name):
        _log(f"⚠️  Skipped rename – table not found: {table_name}")
        return

    if not has_column(table_name, old_name):
        _log(f"⚠️  Skipped rename – source column not found: {table_name}.{old_name}")
        return

    if has_column(table_name, new_name):
        _log(f"⚠️  Skipped rename – target already exists: {table_name}.{new_name}")
        return

    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            old_name,
            new_column_name=new_name,
            existing_type=existing_type,
            existing_nullable=existing_nullable,
        )
    _log(f"🔤  Renamed column: {table_name}.{old_name} → {new_name}")


# ─────────────────────────────────────────────────────────────────────────────
# Misc
# ─────────────────────────────────────────────────────────────────────────────


def safe_execute_sql(sql: str) -> None:
    """
    Execute raw SQL and print a short log.
    Use for guarded UPDATE backfills etc.
    Caller is responsible for table/column checks.
    """
    bind = op.get_bind()
    _log(f"🛠️  Executing SQL: {sql}")
    bind.exec_driver_sql(sql)


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────


def _log(msg: str) -> None:
    print(f"[alembic.safe_ddl] {msg}", flush=True)
