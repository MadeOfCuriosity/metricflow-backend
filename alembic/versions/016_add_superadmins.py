"""Add superadmins table for platform-level administration

Revision ID: 016
Revises: 015
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "superadmins",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("google_id", sa.String(255), nullable=True),
        sa.Column("picture", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by_email", sa.String(255), nullable=True),
    )
    op.create_index("ix_superadmins_email", "superadmins", ["email"])
    op.create_index("ix_superadmins_google_id", "superadmins", ["google_id"])


def downgrade() -> None:
    op.drop_index("ix_superadmins_google_id", table_name="superadmins")
    op.drop_index("ix_superadmins_email", table_name="superadmins")
    op.drop_table("superadmins")
