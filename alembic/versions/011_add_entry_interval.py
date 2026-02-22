"""Add entry_interval to data_fields for configurable data entry frequency

Revision ID: 011
Revises: 010
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add entry_interval column with server default so existing rows get 'daily'
    op.add_column(
        'data_fields',
        sa.Column('entry_interval', sa.String(20), nullable=False, server_default='daily')
    )
    # Index for filtering fields by interval in the entry form
    op.create_index('ix_data_fields_entry_interval', 'data_fields', ['entry_interval'])


def downgrade() -> None:
    op.drop_index('ix_data_fields_entry_interval', table_name='data_fields')
    op.drop_column('data_fields', 'entry_interval')
