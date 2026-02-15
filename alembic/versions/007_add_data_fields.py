"""Add data_fields, data_field_entries, and kpi_data_fields tables

Revision ID: 007
Revises: 006
Create Date: 2024-02-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create data_fields table
    op.create_table(
        'data_fields',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('room_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('variable_name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('unit', sa.String(50), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'variable_name', name='uq_data_field_org_variable'),
    )
    op.create_index('ix_data_fields_org_id', 'data_fields', ['org_id'])
    op.create_index('ix_data_fields_room_id', 'data_fields', ['room_id'])

    # 2. Create data_field_entries table
    op.create_table(
        'data_field_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('data_field_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('entered_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['data_field_id'], ['data_fields.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entered_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'data_field_id', 'date', name='uq_field_entry_org_field_date'),
    )
    op.create_index('ix_data_field_entries_org_id', 'data_field_entries', ['org_id'])
    op.create_index('ix_data_field_entries_data_field_id', 'data_field_entries', ['data_field_id'])
    op.create_index('ix_data_field_entries_date', 'data_field_entries', ['date'])
    op.create_index('ix_data_field_entries_org_field_date', 'data_field_entries', ['org_id', 'data_field_id', 'date'])

    # 3. Create kpi_data_fields join table
    op.create_table(
        'kpi_data_fields',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kpi_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('data_field_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('variable_name', sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(['kpi_id'], ['kpi_definitions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['data_field_id'], ['data_fields.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kpi_id', 'data_field_id', name='uq_kpi_data_field'),
    )
    op.create_index('ix_kpi_data_fields_kpi_id', 'kpi_data_fields', ['kpi_id'])
    op.create_index('ix_kpi_data_fields_data_field_id', 'kpi_data_fields', ['data_field_id'])

    # 4. Data migration: Create DataFields from existing KPI input_fields
    # and decompose data_entries into data_field_entries
    #
    # This is done via raw SQL for performance and to avoid ORM dependency in migrations.
    # The migration:
    #   a) Collects all unique (org_id, variable_name) pairs from kpi_definitions.input_fields
    #   b) Creates a DataField for each unique variable per org
    #   c) Links KPIs to their DataFields via kpi_data_fields
    #   d) Decomposes data_entries.values JSONB into individual data_field_entries rows

    conn = op.get_bind()

    # Step a+b: Create DataFields from existing KPI input_fields
    # Get all KPIs with their input_fields and first room assignment
    kpis = conn.execute(sa.text("""
        SELECT k.id, k.org_id, k.input_fields, k.created_by,
               rka.room_id as first_room_id
        FROM kpi_definitions k
        LEFT JOIN LATERAL (
            SELECT room_id FROM room_kpi_assignments
            WHERE kpi_id = k.id
            LIMIT 1
        ) rka ON true
        ORDER BY k.org_id, k.created_at
    """)).fetchall()

    # Track created data fields: (org_id, variable_name) -> data_field_id
    created_fields = {}

    for kpi in kpis:
        org_id = kpi.org_id
        input_fields = kpi.input_fields or []
        room_id = kpi.first_room_id

        for var_name in input_fields:
            field_key = (str(org_id), var_name)
            if field_key not in created_fields:
                # Create a new DataField
                # Prettify variable name for display: "deals_closed" -> "Deals Closed"
                display_name = var_name.replace('_', ' ').title()
                result = conn.execute(sa.text("""
                    INSERT INTO data_fields (id, org_id, room_id, name, variable_name, created_by, created_at)
                    VALUES (gen_random_uuid(), :org_id, :room_id, :name, :variable_name, :created_by, NOW())
                    ON CONFLICT (org_id, variable_name) DO NOTHING
                    RETURNING id
                """), {
                    "org_id": org_id,
                    "room_id": room_id,
                    "name": display_name,
                    "variable_name": var_name,
                    "created_by": kpi.created_by,
                })
                row = result.fetchone()
                if row:
                    created_fields[field_key] = row.id
                else:
                    # Already exists (race condition or duplicate), fetch it
                    existing = conn.execute(sa.text("""
                        SELECT id FROM data_fields
                        WHERE org_id = :org_id AND variable_name = :variable_name
                    """), {"org_id": org_id, "variable_name": var_name}).fetchone()
                    if existing:
                        created_fields[field_key] = existing.id

    # Step c: Create kpi_data_fields mappings
    for kpi in kpis:
        org_id = kpi.org_id
        input_fields = kpi.input_fields or []

        for var_name in input_fields:
            field_key = (str(org_id), var_name)
            data_field_id = created_fields.get(field_key)
            if data_field_id:
                conn.execute(sa.text("""
                    INSERT INTO kpi_data_fields (id, kpi_id, data_field_id, variable_name)
                    VALUES (gen_random_uuid(), :kpi_id, :data_field_id, :variable_name)
                    ON CONFLICT (kpi_id, data_field_id) DO NOTHING
                """), {
                    "kpi_id": kpi.id,
                    "data_field_id": data_field_id,
                    "variable_name": var_name,
                })

    # Step d: Decompose data_entries.values into data_field_entries
    # For each data_entry, extract individual field values and insert into data_field_entries
    conn.execute(sa.text("""
        INSERT INTO data_field_entries (id, org_id, data_field_id, date, value, entered_by, created_at)
        SELECT
            gen_random_uuid(),
            de.org_id,
            df.id,
            de.date,
            (de.values->>df.variable_name)::float,
            de.entered_by,
            de.created_at
        FROM data_entries de
        JOIN kpi_data_fields kdf ON kdf.kpi_id = de.kpi_id
        JOIN data_fields df ON df.id = kdf.data_field_id
        WHERE de.values ? df.variable_name
          AND (de.values->>df.variable_name) IS NOT NULL
        ON CONFLICT (org_id, data_field_id, date) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_table('kpi_data_fields')
    op.drop_table('data_field_entries')
    op.drop_table('data_fields')
