"""Add org_app_installations and app_run_records tables for the Apps/Extensions framework

Revision ID: 019
Revises: 018
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_app_installations",
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
        sa.Column("app_key", sa.String(100), nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "entitlement_status",
            sa.String(20),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("secret_config_encrypted", sa.Text, nullable=True),
        sa.Column(
            "installed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "installed_at", sa.DateTime, nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime, nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_org_app_installations_org_id", "org_app_installations", ["org_id"])
    op.create_index("ix_org_app_installations_app_key", "org_app_installations", ["app_key"])
    op.create_unique_constraint(
        "uq_org_app_installations_org_app", "org_app_installations", ["org_id", "app_key"]
    )

    op.create_table(
        "app_run_records",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "installation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("org_app_installations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("app_key", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column(
            "triggered_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(150), nullable=False),
        sa.Column(
            "started_at", sa.DateTime, nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
    )
    op.create_index("ix_app_run_records_installation_id", "app_run_records", ["installation_id"])
    op.create_index("ix_app_run_records_org_id", "app_run_records", ["org_id"])
    op.create_index("ix_app_run_records_started_at", "app_run_records", ["started_at"])
    op.create_index("ix_app_run_records_status", "app_run_records", ["status"])
    op.create_unique_constraint(
        "uq_app_run_records_installation_idempotency",
        "app_run_records",
        ["installation_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_app_run_records_installation_idempotency", "app_run_records", type_="unique"
    )
    op.drop_index("ix_app_run_records_status", table_name="app_run_records")
    op.drop_index("ix_app_run_records_started_at", table_name="app_run_records")
    op.drop_index("ix_app_run_records_org_id", table_name="app_run_records")
    op.drop_index("ix_app_run_records_installation_id", table_name="app_run_records")
    op.drop_table("app_run_records")

    op.drop_constraint(
        "uq_org_app_installations_org_app", "org_app_installations", type_="unique"
    )
    op.drop_index("ix_org_app_installations_app_key", table_name="org_app_installations")
    op.drop_index("ix_org_app_installations_org_id", table_name="org_app_installations")
    op.drop_table("org_app_installations")
