"""Add plan fields to organizations and webhook_events idempotency table

Revision ID: 014
Revises: 013
Create Date: 2026-04-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plan mirror on organizations for fast entitlement checks
    op.add_column("organizations", sa.Column("plan_code", sa.String(50), nullable=True))
    op.add_column("organizations", sa.Column("plan_status", sa.String(30), nullable=True))
    op.add_column("organizations", sa.Column("plan_current_end", sa.DateTime, nullable=True))

    # Webhook event idempotency log
    op.create_table(
        "webhook_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "provider", "event_id", name="uq_webhook_events_provider_event_id"
        ),
    )
    op.create_index("ix_webhook_events_received_at", "webhook_events", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_webhook_events_received_at", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_column("organizations", "plan_current_end")
    op.drop_column("organizations", "plan_status")
    op.drop_column("organizations", "plan_code")
