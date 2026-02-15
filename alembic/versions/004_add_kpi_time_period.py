"""Add time_period column to kpi_definitions table

Revision ID: 004
Revises: 003
Create Date: 2024-01-15

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the enum type for time_period
    time_period_enum = sa.Enum(
        'daily', 'weekly', 'monthly', 'quarterly', 'other',
        name='time_period_enum'
    )
    time_period_enum.create(op.get_bind(), checkfirst=True)

    # Add time_period column with default value 'daily'
    op.add_column(
        'kpi_definitions',
        sa.Column(
            'time_period',
            sa.Enum('daily', 'weekly', 'monthly', 'quarterly', 'other', name='time_period_enum'),
            nullable=False,
            server_default='daily'
        )
    )


def downgrade() -> None:
    # Remove the column
    op.drop_column('kpi_definitions', 'time_period')

    # Drop the enum type
    time_period_enum = sa.Enum(name='time_period_enum')
    time_period_enum.drop(op.get_bind(), checkfirst=True)
