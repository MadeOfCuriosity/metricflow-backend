"""Add subscriptions table for Razorpay billing

Revision ID: 013
Revises: 012
Create Date: 2026-04-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_code", sa.String(50), nullable=False),
        sa.Column("razorpay_plan_id", sa.String(100), nullable=False),
        sa.Column(
            "razorpay_subscription_id", sa.String(100), nullable=False, unique=True
        ),
        sa.Column("razorpay_customer_id", sa.String(100), nullable=True),
        sa.Column(
            "status", sa.String(30), nullable=False, server_default="created"
        ),
        sa.Column("total_count", sa.Integer, nullable=True),
        sa.Column("paid_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("current_start", sa.DateTime, nullable=True),
        sa.Column("current_end", sa.DateTime, nullable=True),
        sa.Column("ended_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_subscriptions_org_id", "subscriptions", ["org_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_org_id", table_name="subscriptions")
    op.drop_table("subscriptions")
