"""add_decision_telemetry_to_assistants_table_convert_agent_mode_to_bool

Revision ID: 6413efed1b18
Revises: 741d86dd5ac8
Create Date: 2026-02-05 00:50:19.823642

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# Import the safe DDL helpers
from migrations.utils.safe_ddl import (add_column_if_missing,
                                       drop_column_if_exists,
                                       safe_alter_column)

# revision identifiers, used by Alembic.
revision: str = "6413efed1b18"
down_revision: Union[str, None] = "741d86dd5ac8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema safely."""

    # --- Table: assistants ---

    # 1. Add the decision_telemetry column
    add_column_if_missing(
        "assistants",
        sa.Column(
            "decision_telemetry",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),  # Defaults to False for existing rows
            comment="Flag to enable/disable detailed decision telemetry logging.",
        ),
    )

    # 2. Convert agent_mode from String/Enum to Boolean
    # Note: Ensure existing data maps correctly to 0/1 before running if table is not empty.
    safe_alter_column(
        "assistants",
        "agent_mode",
        existing_type=mysql.VARCHAR(
            length=255
        ),  # Update length if your existing schema differs
        type_=sa.Boolean(),
        comment="Boolean flag indicating the mode of the agent.",
        nullable=False,  # Assuming a mode is always required
    )


def downgrade() -> None:
    """Downgrade schema safely."""

    # --- Table: assistants ---

    # 1. Revert agent_mode back to String
    safe_alter_column(
        "assistants",
        "agent_mode",
        existing_type=sa.Boolean(),
        type_=mysql.VARCHAR(length=255),  # Revert to original length
        nullable=True,
    )

    # 2. Drop the decision_telemetry column
    drop_column_if_exists("assistants", "decision_telemetry")
