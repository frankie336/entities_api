"""drop platform_tools from assistants

Revision ID: c8adf7bf8fa8
Revises: 0f2bbee38b41
Create Date: 2025-06-29 22:00:51.633891
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8adf7bf8fa8"
down_revision: Union[str, None] = "0f2bbee38b41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("assistants") as batch:
        batch.drop_column("platform_tools")


def downgrade() -> None:
    """Downgrade schema (re-adds the column)."""
    with op.batch_alter_table("assistants") as batch:
        batch.add_column(sa.Column("platform_tools", sa.JSON(), nullable=True))
