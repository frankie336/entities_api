"""Remove thread ---> vector_store relationship

Revision ID: 26a927cbe516
Revises: 3a42e4f129e4
Create Date: 2026-03-08 05:34:08.601782

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# Import SafeDDL helpers
from migrations.utils.safe_ddl import has_table, safe_alter_column

# revision identifiers, used by Alembic.
revision: str = '26a927cbe516'
down_revision: Union[str, None] = '3a42e4f129e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if tables exist before attempting to drop them
    if has_table('thread_vector_stores'):
        op.drop_table('thread_vector_stores')

    if has_table('vector_store_assistants'):
        op.drop_table('vector_store_assistants')

    # Safe column alterations
    safe_alter_column(
        table_name='messages', column_name='content', existing_type=mysql.TEXT(), nullable=False
    )

    safe_alter_column(
        table_name='messages',
        column_name='reasoning',
        existing_type=mysql.LONGTEXT(),
        type_=sa.Text(length=4294967295),
        existing_comment="Stores the internal 'thinking' or reasoning tokens from the model.",
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Safe column alterations for reversion
    safe_alter_column(
        table_name='messages',
        column_name='reasoning',
        existing_type=sa.Text(length=4294967295),
        type_=mysql.LONGTEXT(),
        existing_comment="Stores the internal 'thinking' or reasoning tokens from the model.",
        existing_nullable=True,
    )

    safe_alter_column(
        table_name='messages', column_name='content', existing_type=mysql.TEXT(), nullable=True
    )

    # Check if tables are missing before attempting to create them
    if not has_table('vector_store_assistants'):
        op.create_table(
            'vector_store_assistants',
            sa.Column('vector_store_id', mysql.VARCHAR(length=64), nullable=False),
            sa.Column('assistant_id', mysql.VARCHAR(length=64), nullable=False),
            sa.ForeignKeyConstraint(
                ['assistant_id'], ['assistants.id'], name=op.f('vector_store_assistants_ibfk_2')
            ),
            sa.ForeignKeyConstraint(
                ['vector_store_id'],
                ['vector_stores.id'],
                name=op.f('vector_store_assistants_ibfk_1'),
            ),
            sa.PrimaryKeyConstraint('vector_store_id', 'assistant_id'),
            mysql_collate='utf8mb4_0900_ai_ci',
            mysql_default_charset='utf8mb4',
            mysql_engine='InnoDB',
        )

    if not has_table('thread_vector_stores'):
        op.create_table(
            'thread_vector_stores',
            sa.Column('thread_id', mysql.VARCHAR(length=64), nullable=False),
            sa.Column('vector_store_id', mysql.VARCHAR(length=64), nullable=False),
            sa.ForeignKeyConstraint(
                ['thread_id'], ['threads.id'], name=op.f('thread_vector_stores_ibfk_1')
            ),
            sa.ForeignKeyConstraint(
                ['vector_store_id'], ['vector_stores.id'], name=op.f('thread_vector_stores_ibfk_2')
            ),
            sa.PrimaryKeyConstraint('thread_id', 'vector_store_id'),
            mysql_collate='utf8mb4_0900_ai_ci',
            mysql_default_charset='utf8mb4',
            mysql_engine='InnoDB',
        )
