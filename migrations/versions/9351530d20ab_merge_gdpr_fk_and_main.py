"""merge_gdpr_fk_and_main

Revision ID: 9351530d20ab
Revises: 222cafa3baac, 26a927cbe516
Create Date: 2026-03-08 21:19:48.959897

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9351530d20ab'
down_revision: Union[str, None] = ('222cafa3baac', '26a927cbe516')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
