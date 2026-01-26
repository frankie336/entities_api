"""fix_run_instructions_length

Revision ID: 3b439a3fa9f6
Revises: ac1498a9642c
Create Date: 2026-01-25 16:17:27.831268

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# Import the SafeDDL utilities
from migrations.utils.safe_ddl import safe_alter_column

# revision identifiers, used by Alembic.
revision: str = "3b439a3fa9f6"
down_revision: Union[str, None] = "ac1498a9642c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema using SafeDDL helpers."""

    # 1. Fix messages content nullability
    safe_alter_column("messages", "content", existing_type=mysql.TEXT(), nullable=False)

    # 2. Sync reasoning column type (LongText mapping)
    safe_alter_column(
        "messages",
        "reasoning",
        existing_type=mysql.LONGTEXT(),
        type_=sa.Text(length=4294967295),
        existing_comment="Stores the internal 'thinking' or reasoning tokens from the model.",
        existing_nullable=True,
    )

    # 3. CORE FIX: Increase runs.instructions from 1024 to TEXT
    safe_alter_column(
        "runs",
        "instructions",
        existing_type=mysql.VARCHAR(length=1024),
        type_=sa.Text(),
        existing_nullable=True,
    )

    # 4. Update agent_mode comment
    safe_alter_column(
        "runs",
        "agent_mode",
        existing_type=mysql.VARCHAR(length=32),
        comment="Determines execution logic: 'standard' (Level 2) or 'autonomous' (Level 3).",
        existing_comment="Snapshot of Assistant.agent_mode at run creation.",
        existing_nullable=True,
        existing_server_default=sa.text("'standard'"),
    )


def downgrade() -> None:
    """Downgrade schema using SafeDDL helpers."""

    # 1. Revert agent_mode comment
    safe_alter_column(
        "runs",
        "agent_mode",
        existing_type=mysql.VARCHAR(length=32),
        comment="Snapshot of Assistant.agent_mode at run creation.",
        existing_comment="Determines execution logic: 'standard' (Level 2) or 'autonomous' (Level 3).",
        existing_nullable=True,
        existing_server_default=sa.text("'standard'"),
    )

    # 2. Revert runs.instructions back to VARCHAR(1024)
    safe_alter_column(
        "runs",
        "instructions",
        existing_type=sa.Text(),
        type_=mysql.VARCHAR(length=1024),
        existing_nullable=True,
    )

    # 3. Revert reasoning column type
    safe_alter_column(
        "messages",
        "reasoning",
        existing_type=sa.Text(length=4294967295),
        type_=mysql.LONGTEXT(),
        existing_comment="Stores the internal 'thinking' or reasoning tokens from the model.",
        existing_nullable=True,
    )

    # 4. Revert messages content back to nullable
    safe_alter_column("messages", "content", existing_type=mysql.TEXT(), nullable=True)
