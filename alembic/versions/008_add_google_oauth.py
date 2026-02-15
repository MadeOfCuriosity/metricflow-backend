"""add_google_oauth_columns

Revision ID: 008
Revises: ee495df5c62a
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, None] = 'ee495df5c62a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make password_hash nullable for Google-only users
    op.alter_column('users', 'password_hash',
                    existing_type=sa.String(255),
                    nullable=True)

    # Add Google OAuth columns
    op.add_column('users', sa.Column('google_id', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('auth_provider', sa.String(20), nullable=True, server_default='email'))

    # Index for fast Google ID lookups
    op.create_index('ix_users_google_id', 'users', ['google_id'])

    # Backfill existing users
    op.execute("UPDATE users SET auth_provider = 'email' WHERE auth_provider IS NULL")


def downgrade() -> None:
    op.drop_index('ix_users_google_id', table_name='users')
    op.drop_column('users', 'auth_provider')
    op.drop_column('users', 'google_id')
    op.alter_column('users', 'password_hash',
                    existing_type=sa.String(255),
                    nullable=False)
