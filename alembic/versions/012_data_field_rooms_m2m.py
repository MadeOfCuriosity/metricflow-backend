"""Replace data_fields.room_id with many-to-many data_field_rooms junction table

Revision ID: 012
Revises: 011
Create Date: 2026-02-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Handle duplicate (org_id, variable_name) across different rooms.
    #    If two fields share the same variable_name in an org but different rooms,
    #    rename the later ones by appending the room name slug.
    conn = op.get_bind()
    dupes = conn.execute(sa.text("""
        SELECT df.id, df.variable_name, df.org_id, df.room_id, r.name as room_name
        FROM data_fields df
        LEFT JOIN rooms r ON df.room_id = r.id
        WHERE df.variable_name IN (
            SELECT variable_name
            FROM data_fields
            GROUP BY org_id, variable_name
            HAVING COUNT(*) > 1
        )
        ORDER BY df.org_id, df.variable_name, df.created_at
    """)).fetchall()

    # Group by (org_id, variable_name) — keep the first, rename the rest
    seen: dict[tuple, bool] = {}
    for row in dupes:
        key = (str(row.org_id), row.variable_name)
        if key not in seen:
            seen[key] = True  # keep first occurrence
        else:
            # Rename: append room name slug
            room_slug = (row.room_name or "unassigned").lower().replace(" ", "_")
            new_var = f"{row.variable_name}_{room_slug}"
            new_name_val = f"{row.variable_name} ({row.room_name or 'unassigned'})"
            conn.execute(sa.text(
                "UPDATE data_fields SET variable_name = :new_var, name = :new_name WHERE id = :id"
            ), {"new_var": new_var, "new_name": new_name_val, "id": row.id})

    # 2. Create the junction table
    op.create_table(
        'data_field_rooms',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('data_field_id', UUID(as_uuid=True), sa.ForeignKey('data_fields.id', ondelete='CASCADE'), nullable=False),
        sa.Column('room_id', UUID(as_uuid=True), sa.ForeignKey('rooms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assigned_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_data_field_rooms_data_field_id', 'data_field_rooms', ['data_field_id'])
    op.create_index('ix_data_field_rooms_room_id', 'data_field_rooms', ['room_id'])
    op.create_unique_constraint('uq_data_field_room', 'data_field_rooms', ['data_field_id', 'room_id'])

    # 3. Copy existing room_id assignments into the junction table
    op.execute("""
        INSERT INTO data_field_rooms (id, data_field_id, room_id, assigned_at)
        SELECT gen_random_uuid(), id, room_id, created_at
        FROM data_fields
        WHERE room_id IS NOT NULL
    """)

    # 4. Drop old partial unique indexes on data_fields
    op.execute("DROP INDEX IF EXISTS uq_data_field_org_variable_room")
    op.execute("DROP INDEX IF EXISTS uq_data_field_org_variable_no_room")

    # 5. Add new global unique constraint on (org_id, variable_name)
    op.create_unique_constraint('uq_data_field_org_variable', 'data_fields', ['org_id', 'variable_name'])

    # 6. Drop room_id column and its index from data_fields
    op.drop_index('ix_data_fields_room_id', table_name='data_fields')
    op.drop_constraint('data_fields_room_id_fkey', 'data_fields', type_='foreignkey')
    op.drop_column('data_fields', 'room_id')


def downgrade() -> None:
    # Add room_id back to data_fields
    op.add_column(
        'data_fields',
        sa.Column('room_id', UUID(as_uuid=True), sa.ForeignKey('rooms.id', ondelete='SET NULL'), nullable=True)
    )
    op.create_index('ix_data_fields_room_id', 'data_fields', ['room_id'])

    # Copy first room assignment back to room_id
    op.execute("""
        UPDATE data_fields df
        SET room_id = (
            SELECT dfr.room_id
            FROM data_field_rooms dfr
            WHERE dfr.data_field_id = df.id
            ORDER BY dfr.assigned_at
            LIMIT 1
        )
    """)

    # Restore partial unique indexes
    op.drop_constraint('uq_data_field_org_variable', 'data_fields', type_='unique')
    op.execute("""
        CREATE UNIQUE INDEX uq_data_field_org_variable_room
        ON data_fields (org_id, variable_name, room_id)
        WHERE room_id IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_data_field_org_variable_no_room
        ON data_fields (org_id, variable_name)
        WHERE room_id IS NULL
    """)

    # Drop junction table
    op.drop_table('data_field_rooms')
