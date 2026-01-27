"""convert truncation_strategy to VARCHAR(16) default auto

Revision ID: c34a9a215b5d
Revises: dc84d53c3c46
Create Date: 2025-10-12 17:02:41.526506
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from migrations.utils.safe_ddl import safe_alter_column

# revision identifiers, used by Alembic.
revision: str = "c34a9a215b5d"
down_revision: Union[str, None] = "dc84d53c3c46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # messages.function_call → NOT NULL (guarded)
    safe_alter_column(
        "messages",
        "function_call",
        existing_type=mysql.TEXT(),
        nullable=False,
    )

    # runs.truncation_strategy: JSON → VARCHAR(16), NOT NULL, DEFAULT 'auto' (guarded)
    safe_alter_column(
        "runs",
        "truncation_strategy",
        existing_type=mysql.JSON(),
        type_=sa.String(length=16),
        nullable=False,
        server_default="auto",
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""

    # runs.truncation_strategy: VARCHAR(16) → JSON, nullable, clear default (guarded)
    safe_alter_column(
        "runs",
        "truncation_strategy",
        existing_type=sa.String(length=16),
        type_=mysql.JSON(),
        nullable=True,
        server_default=None,
    )

    # messages.function_call → nullable (guarded)
    safe_alter_column(
        "messages",
        "function_call",
        existing_type=mysql.TEXT(),
        nullable=True,
    )
