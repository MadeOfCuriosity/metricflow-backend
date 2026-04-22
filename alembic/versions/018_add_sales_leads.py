"""Add sales_leads table for inbound contact-sales captures

Revision ID: 018
Revises: 017
Create Date: 2026-04-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sales_leads",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("team_size", sa.String(50), nullable=True),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            server_default="enterprise_contact",
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_sales_leads_status", "sales_leads", ["status"])
    op.create_index("ix_sales_leads_email", "sales_leads", ["email"])


def downgrade() -> None:
    op.drop_index("ix_sales_leads_email", table_name="sales_leads")
    op.drop_index("ix_sales_leads_status", table_name="sales_leads")
    op.drop_table("sales_leads")
