"""Add room_id to data_entries for room-scoped KPI tracking and aggregation

Revision ID: 010
Revises: 009
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add room_id column to data_entries
    op.add_column(
        'data_entries',
        sa.Column('room_id', UUID(as_uuid=True), sa.ForeignKey('rooms.id', ondelete='SET NULL'), nullable=True)
    )
    op.create_index('ix_data_entries_room_id', 'data_entries', ['room_id'])

    # 2. Replace unique constraint on data_entries with partial unique indexes
    op.drop_constraint('uq_data_entry_org_kpi_date', 'data_entries', type_='unique')

    # Entries WITH a room_id: unique per (org, kpi, date, room)
    op.execute("""
        CREATE UNIQUE INDEX uq_data_entry_org_kpi_date_room
        ON data_entries (org_id, kpi_id, date, room_id)
        WHERE room_id IS NOT NULL
    """)

    # Entries WITHOUT a room_id (org-level): unique per (org, kpi, date)
    op.execute("""
        CREATE UNIQUE INDEX uq_data_entry_org_kpi_date_no_room
        ON data_entries (org_id, kpi_id, date)
        WHERE room_id IS NULL
    """)

    # Composite index for aggregation queries
    op.create_index(
        'ix_data_entries_org_kpi_room_date',
        'data_entries',
        ['org_id', 'kpi_id', 'room_id', 'date']
    )

    # 3. Add aggregation_method to room_kpi_assignments
    op.add_column(
        'room_kpi_assignments',
        sa.Column('aggregation_method', sa.String(20), nullable=False, server_default='sum')
    )

    # 4. Relax data_fields uniqueness: variable_name unique per (org, room) instead of per org
    op.drop_constraint('uq_data_field_org_variable', 'data_fields', type_='unique')

    # Fields WITH a room_id: unique per (org, variable_name, room)
    op.execute("""
        CREATE UNIQUE INDEX uq_data_field_org_variable_room
        ON data_fields (org_id, variable_name, room_id)
        WHERE room_id IS NOT NULL
    """)

    # Fields WITHOUT a room_id (org-level): unique per (org, variable_name)
    op.execute("""
        CREATE UNIQUE INDEX uq_data_field_org_variable_no_room
        ON data_fields (org_id, variable_name)
        WHERE room_id IS NULL
    """)


def downgrade() -> None:
    # Restore data_fields constraint
    op.execute("DROP INDEX IF EXISTS uq_data_field_org_variable_room")
    op.execute("DROP INDEX IF EXISTS uq_data_field_org_variable_no_room")
    op.create_unique_constraint('uq_data_field_org_variable', 'data_fields', ['org_id', 'variable_name'])

    # Remove aggregation_method from room_kpi_assignments
    op.drop_column('room_kpi_assignments', 'aggregation_method')

    # Restore data_entries constraint
    op.drop_index('ix_data_entries_org_kpi_room_date', table_name='data_entries')
    op.execute("DROP INDEX IF EXISTS uq_data_entry_org_kpi_date_room")
    op.execute("DROP INDEX IF EXISTS uq_data_entry_org_kpi_date_no_room")
    op.create_unique_constraint('uq_data_entry_org_kpi_date', 'data_entries', ['org_id', 'kpi_id', 'date'])

    op.drop_index('ix_data_entries_room_id', table_name='data_entries')
    op.drop_column('data_entries', 'room_id')
