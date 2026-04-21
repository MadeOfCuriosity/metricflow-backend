"""Add superadmin audit log, notification campaigns, and dismissals

Revision ID: 017
Revises: 016
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "superadmin_audit_log",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "superadmin_id",
            UUID(as_uuid=True),
            sa.ForeignKey("superadmins.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("superadmin_email", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("target_id", sa.String(100), nullable=True),
        sa.Column("details", JSONB, nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_audit_superadmin_id", "superadmin_audit_log", ["superadmin_id"]
    )
    op.create_index("ix_audit_action", "superadmin_audit_log", ["action"])
    op.create_index("ix_audit_created_at", "superadmin_audit_log", ["created_at"])

    op.create_table(
        "notification_campaigns",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_by_superadmin_id",
            UUID(as_uuid=True),
            sa.ForeignKey("superadmins.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_email", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("cta_label", sa.String(100), nullable=True),
        sa.Column("cta_url", sa.String(512), nullable=True),
        # channel: in_app | email
        sa.Column(
            "channel", sa.String(20), nullable=False, server_default=sa.text("'in_app'")
        ),
        # severity: info | warning | success | announcement
        sa.Column(
            "severity", sa.String(20), nullable=False, server_default=sa.text("'info'")
        ),
        # status: draft | sent | cancelled
        sa.Column(
            "status", sa.String(20), nullable=False, server_default=sa.text("'draft'")
        ),
        # target filter snapshot (industries, plans, plan_statuses, all)
        sa.Column("target_filter", JSONB, nullable=True),
        sa.Column("recipient_org_count", sa.Integer, nullable=True),
        sa.Column("recipient_user_count", sa.Integer, nullable=True),
        sa.Column("sent_at", sa.DateTime, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_campaigns_status", "notification_campaigns", ["status"]
    )
    op.create_index(
        "ix_campaigns_created_at", "notification_campaigns", ["created_at"]
    )

    # Snapshot of which orgs/users a sent campaign targets.
    op.create_table(
        "notification_campaign_orgs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("notification_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_campaign_orgs_campaign",
        "notification_campaign_orgs",
        ["campaign_id"],
    )
    op.create_index(
        "ix_campaign_orgs_org", "notification_campaign_orgs", ["org_id"]
    )
    op.create_unique_constraint(
        "uq_campaign_org",
        "notification_campaign_orgs",
        ["campaign_id", "org_id"],
    )

    # Tracks which users have dismissed which campaigns.
    op.create_table(
        "notification_dismissals",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "campaign_id",
            UUID(as_uuid=True),
            sa.ForeignKey("notification_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dismissed_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_dismissal_user_campaign",
        "notification_dismissals",
        ["user_id", "campaign_id"],
    )


def downgrade() -> None:
    op.drop_table("notification_dismissals")
    op.drop_index("ix_campaign_orgs_org", table_name="notification_campaign_orgs")
    op.drop_index("ix_campaign_orgs_campaign", table_name="notification_campaign_orgs")
    op.drop_table("notification_campaign_orgs")
    op.drop_index("ix_campaigns_created_at", table_name="notification_campaigns")
    op.drop_index("ix_campaigns_status", table_name="notification_campaigns")
    op.drop_table("notification_campaigns")
    op.drop_index("ix_audit_created_at", table_name="superadmin_audit_log")
    op.drop_index("ix_audit_action", table_name="superadmin_audit_log")
    op.drop_index("ix_audit_superadmin_id", table_name="superadmin_audit_log")
    op.drop_table("superadmin_audit_log")
