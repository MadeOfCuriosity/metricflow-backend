"""Convert is_revoked from String to Boolean

Revision ID: 009
Revises: 008
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add temporary boolean column
    op.add_column('refresh_tokens', sa.Column('is_revoked_bool', sa.Boolean(), server_default='false', nullable=False))

    # Migrate data: 'Y' -> True, everything else -> False
    op.execute("UPDATE refresh_tokens SET is_revoked_bool = CASE WHEN is_revoked = 'Y' THEN true ELSE false END")

    # Drop old column and rename new one
    op.drop_index('ix_refresh_tokens_user_id_revoked', table_name='refresh_tokens')
    op.drop_column('refresh_tokens', 'is_revoked')
    op.alter_column('refresh_tokens', 'is_revoked_bool', new_column_name='is_revoked')
    op.create_index('ix_refresh_tokens_user_id_revoked', 'refresh_tokens', ['user_id', 'is_revoked'])


def downgrade() -> None:
    # Convert back to String
    op.add_column('refresh_tokens', sa.Column('is_revoked_str', sa.String(1), nullable=True, server_default='N'))
    op.execute("UPDATE refresh_tokens SET is_revoked_str = CASE WHEN is_revoked = true THEN 'Y' ELSE 'N' END")
    op.drop_index('ix_refresh_tokens_user_id_revoked', table_name='refresh_tokens')
    op.drop_column('refresh_tokens', 'is_revoked')
    op.alter_column('refresh_tokens', 'is_revoked_str', new_column_name='is_revoked')
    op.create_index('ix_refresh_tokens_user_id_revoked', 'refresh_tokens', ['user_id', 'is_revoked'])
