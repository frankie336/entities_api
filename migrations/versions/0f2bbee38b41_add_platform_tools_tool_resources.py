"""add ptool_handlers + tool_resources

Revision ID: 0f2bbee38b41
Revises: e844e0ceaba2
Create Date: 2025-05-01 12:59:08.713259

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError  # Import the exception

# revision identifiers, used by Alembic.
revision: str = "0f2bbee38b41"
down_revision: Union[str, None] = "e844e0ceaba2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # --- Idempotent check for add_column ---
    try:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'assistants' AND COLUMN_NAME = 'tool_resources'"
            )
        )
        if result.scalar() == 0:
            op.add_column(
                "assistants",
                sa.Column(
                    "tool_resources",
                    sa.JSON(),
                    nullable=True,
                    comment='Resource map keyed by tool type, e.g. {"file_search": {"vector_store_ids": ["vs_123","vs_456"]}}',
                ),
            )
    except Exception as e:
        print(
            f"Could not add column 'tool_resources', probably already exists. Error: {e}"
        )

    # --- Idempotent wrapper for alter_column on 'assistants' ---
    try:
        op.alter_column(
            "assistants",
            "ptool_handlers",
            existing_type=mysql.JSON(),
            comment='Optional array of inline tool specs, e.g. [{"type": "file_search", "vector_store_ids": ["vs_123"]}]',
            existing_comment='Optional array of inline tool specs, e.g. [{"type": "file_search", "vector_store_ids": ["..."]}]',
            existing_nullable=True,
        )
    except Exception as e:
        print(
            f"Could not alter column 'ptool_handlers'. Assuming it's already in the correct state. Error: {e}"
        )

    # --- Idempotent wrapper for alter_column on 'messages' ---
    try:
        op.alter_column(
            "messages", "content", existing_type=mysql.TEXT(), nullable=False
        )
    except Exception as e:
        print(
            f"Could not alter column 'content' on 'messages'. Assuming it's already in the correct state. Error: {e}"
        )


def downgrade() -> None:
    """Downgrade schema."""
    # We apply the same fault-tolerant logic to the downgrade path.
    try:
        op.alter_column(
            "messages", "content", existing_type=mysql.TEXT(), nullable=True
        )
    except Exception as e:
        print(
            f"Could not alter column 'content' on 'messages' during downgrade. Error: {e}"
        )

    try:
        op.alter_column(
            "assistants",
            "ptool_handlers",
            existing_type=mysql.JSON(),
            comment='Optional array of inline tool specs, e.g. [{"type": "file_search", "vector_store_ids": ["..."]}]',
            existing_comment='Optional array of inline tool specs, e.g. [{"type": "file_search", "vector_store_ids": ["vs_123"]}]',
            existing_nullable=True,
        )
    except Exception as e:
        print(f"Could not alter column 'ptool_handlers' during downgrade. Error: {e}")

    try:
        conn = op.get_bind()
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'assistants' AND COLUMN_NAME = 'tool_resources'"
            )
        )
        if result.scalar() > 0:
            op.drop_column("assistants", "tool_resources")
    except Exception as e:
        print(f"Could not drop column 'tool_resources' during downgrade. Error: {e}")
