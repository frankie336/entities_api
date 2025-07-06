"""baseline schema

Revision ID: e844e0ceaba2
Revises: eed80604f05c
Create Date: 2025-05-01 12:54:37.045298

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e844e0ceaba2"
down_revision: Union[str, None] = "eed80604f05c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
