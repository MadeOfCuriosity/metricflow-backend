"""Add user roles and user_room_assignments table

Revision ID: 006
Revises: 005
Create Date: 2024-01-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add role column to users table
    # Default to 'admin' for backward compatibility (existing users become admins)
    op.add_column(
        'users',
        sa.Column('role', sa.String(20), nullable=False, server_default='admin')
    )
    op.create_index('ix_users_role', 'users', ['role'])

    # Create user_room_assignments table
    op.create_table(
        'user_room_assignments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('room_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('rooms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('assigned_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_index('ix_user_room_assignments_user_id', 'user_room_assignments', ['user_id'])
    op.create_index('ix_user_room_assignments_room_id', 'user_room_assignments', ['room_id'])
    op.create_unique_constraint('uq_user_room_assignment', 'user_room_assignments', ['user_id', 'room_id'])


def downgrade() -> None:
    # Drop user_room_assignments table
    op.drop_table('user_room_assignments')

    # Remove role column from users table
    op.drop_index('ix_users_role', 'users')
    op.drop_column('users', 'role')
