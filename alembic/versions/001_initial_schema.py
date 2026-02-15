"""Initial schema for MetricFlow

Revision ID: 001_initial_schema
Revises:
Create Date: 2024-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create organizations table
    op.create_table(
        'organizations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('industry', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('role_label', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('org_id', 'email', name='uq_user_org_email'),
    )
    op.create_index('ix_users_org_id', 'users', ['org_id'])
    op.create_index('ix_users_email', 'users', ['email'])

    # Create kpi_definitions table
    op.create_table(
        'kpi_definitions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('formula', sa.String(500), nullable=False),
        sa.Column('input_fields', postgresql.JSONB(), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('is_preset', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_kpi_definitions_org_id', 'kpi_definitions', ['org_id'])
    op.create_index('ix_kpi_definitions_category', 'kpi_definitions', ['category'])
    op.create_index('ix_kpi_definitions_is_preset', 'kpi_definitions', ['is_preset'])

    # Create data_entries table
    op.create_table(
        'data_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kpi_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('kpi_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('values', postgresql.JSONB(), nullable=False),
        sa.Column('calculated_value', sa.Float(), nullable=False),
        sa.Column('entered_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('org_id', 'kpi_id', 'date', name='uq_data_entry_org_kpi_date'),
    )
    op.create_index('ix_data_entries_org_id', 'data_entries', ['org_id'])
    op.create_index('ix_data_entries_kpi_id', 'data_entries', ['kpi_id'])
    op.create_index('ix_data_entries_date', 'data_entries', ['date'])
    op.create_index('ix_data_entries_org_kpi_date', 'data_entries', ['org_id', 'kpi_id', 'date'])

    # Create thresholds table
    op.create_table(
        'thresholds',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('kpi_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('kpi_definitions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('threshold_type', sa.String(50), nullable=False),
        sa.Column('params', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_thresholds_kpi_id', 'thresholds', ['kpi_id'])

    # Create insights table
    op.create_table(
        'insights',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kpi_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('kpi_definitions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('insight_text', sa.Text(), nullable=False),
        sa.Column('priority', sa.String(20), nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_insights_org_id', 'insights', ['org_id'])
    op.create_index('ix_insights_kpi_id', 'insights', ['kpi_id'])
    op.create_index('ix_insights_priority', 'insights', ['priority'])
    op.create_index('ix_insights_generated_at', 'insights', ['generated_at'])


def downgrade() -> None:
    op.drop_table('insights')
    op.drop_table('thresholds')
    op.drop_table('data_entries')
    op.drop_table('kpi_definitions')
    op.drop_table('users')
    op.drop_table('organizations')
