"""baseline schema

Revision ID: eed80604f05c
Revises:
Create Date: 2025‑05‑01 12:53:21.565924
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "eed80604f05c"
down_revision: Union[str | None] = None
branch_labels: Union[str | Sequence[str] | None] = None
depends_on: Union[str | Sequence[str] | None] = None


def upgrade() -> None:
    """Initial baseline: no‑op (all tables already created)."""
    pass


def downgrade() -> None:
    """Reverse baseline – also a no‑op."""
    pass
