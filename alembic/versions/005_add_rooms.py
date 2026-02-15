"""Add rooms table and room_kpi_assignments table

Revision ID: 005
Revises: 004
Create Date: 2024-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create rooms table
    op.create_table(
        'rooms',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('parent_room_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rooms.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_rooms_org_id', 'rooms', ['org_id'])
    op.create_index('ix_rooms_parent_room_id', 'rooms', ['parent_room_id'])
    op.create_unique_constraint('uq_room_org_name_parent', 'rooms', ['org_id', 'name', 'parent_room_id'])

    # Create room_kpi_assignments table
    op.create_table(
        'room_kpi_assignments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('room_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rooms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kpi_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('kpi_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('assigned_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_index('ix_room_kpi_assignments_room_id', 'room_kpi_assignments', ['room_id'])
    op.create_index('ix_room_kpi_assignments_kpi_id', 'room_kpi_assignments', ['kpi_id'])
    op.create_unique_constraint('uq_room_kpi_assignment', 'room_kpi_assignments', ['room_id', 'kpi_id'])

    # Add is_shared column to kpi_definitions
    op.add_column(
        'kpi_definitions',
        sa.Column('is_shared', sa.Boolean(), nullable=False, server_default='false')
    )
    op.create_index('ix_kpi_definitions_is_shared', 'kpi_definitions', ['is_shared'])


def downgrade() -> None:
    # Remove is_shared from kpi_definitions
    op.drop_index('ix_kpi_definitions_is_shared', 'kpi_definitions')
    op.drop_column('kpi_definitions', 'is_shared')

    # Drop room_kpi_assignments table
    op.drop_table('room_kpi_assignments')

    # Drop rooms table
    op.drop_table('rooms')
