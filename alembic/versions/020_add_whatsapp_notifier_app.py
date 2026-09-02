"""Add whatsapp_recipients, whatsapp_suppressions, whatsapp_send_logs for
the WhatsApp Notifier app

Revision ID: 020
Revises: 019
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_recipients",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id", UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_whatsapp_recipients_org_id", "whatsapp_recipients", ["org_id"])
    op.create_index("ix_whatsapp_recipients_org_phone", "whatsapp_recipients", ["org_id", "phone"])

    op.create_table(
        "whatsapp_suppressions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id", UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_whatsapp_suppressions_org_id", "whatsapp_suppressions", ["org_id"])
    op.create_unique_constraint(
        "uq_whatsapp_suppressions_org_phone", "whatsapp_suppressions", ["org_id", "phone"]
    )

    op.create_table(
        "whatsapp_send_logs",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "org_id", UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "run_id", UUID(as_uuid=True),
            sa.ForeignKey("app_run_records.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column(
            "recipient_id", UUID(as_uuid=True),
            sa.ForeignKey("whatsapp_recipients.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("recipient_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("data_value", sa.String(255), nullable=True),
        sa.Column("template_used", sa.String(255), nullable=True),
        sa.Column("whatsapp_message_id", sa.String(255), nullable=True),
        sa.Column("delivery_status", sa.String(30), nullable=False, server_default="failed"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("period_bucket", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_whatsapp_send_logs_org_id", "whatsapp_send_logs", ["org_id"])
    op.create_index("ix_whatsapp_send_logs_run_id", "whatsapp_send_logs", ["run_id"])
    op.create_index(
        "ix_whatsapp_send_logs_recipient_period", "whatsapp_send_logs", ["recipient_id", "period_bucket"]
    )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_send_logs_recipient_period", table_name="whatsapp_send_logs")
    op.drop_index("ix_whatsapp_send_logs_run_id", table_name="whatsapp_send_logs")
    op.drop_index("ix_whatsapp_send_logs_org_id", table_name="whatsapp_send_logs")
    op.drop_table("whatsapp_send_logs")

    op.drop_constraint("uq_whatsapp_suppressions_org_phone", "whatsapp_suppressions", type_="unique")
    op.drop_index("ix_whatsapp_suppressions_org_id", table_name="whatsapp_suppressions")
    op.drop_table("whatsapp_suppressions")

    op.drop_index("ix_whatsapp_recipients_org_phone", table_name="whatsapp_recipients")
    op.drop_index("ix_whatsapp_recipients_org_id", table_name="whatsapp_recipients")
    op.drop_table("whatsapp_recipients")
