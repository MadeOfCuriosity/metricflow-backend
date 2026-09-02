import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class WhatsAppSendLog(Base):
    """Per-recipient send attempt record for the WhatsApp Notifier app.
    Required for correctness first: it's what makes per-recipient dedup
    possible so a retried or overlapping run never re-sends to the same
    recipient within the same schedule period. It doubles as a send-history
    audit trail, but analytics on top of it is not built here.
    """
    __tablename__ = "whatsapp_send_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("app_run_records.id", ondelete="CASCADE"), nullable=True)
    recipient_id = Column(UUID(as_uuid=True), ForeignKey("whatsapp_recipients.id", ondelete="SET NULL"), nullable=True)

    recipient_name = Column(String(255), nullable=True)  # recipient's name at send time, for a human-readable log
    phone = Column(String(32), nullable=False)  # full E.164; UIs must mask this (show last 4 only)
    data_value = Column(String(255), nullable=True)  # the KPI/DataField value that was sent, as text

    template_used = Column(String(255), nullable=True)
    whatsapp_message_id = Column(String(255), nullable=True)

    # "sent" | "failed" | "skipped_suppressed" | "skipped_duplicate"
    delivery_status = Column(String(30), nullable=False, default="failed")
    error = Column(Text, nullable=True)

    # Deterministic bucket of the schedule interval this send belongs to
    # (same scheme as AppRunRecord.idempotency_key for scheduled runs) — the
    # unit that "already sent this period" dedup checks against.
    period_bucket = Column(String(50), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_whatsapp_send_logs_org_id", "org_id"),
        Index("ix_whatsapp_send_logs_run_id", "run_id"),
        Index("ix_whatsapp_send_logs_recipient_period", "recipient_id", "period_bucket"),
    )

    def __repr__(self):
        return f"<WhatsAppSendLog org={self.org_id} status={self.delivery_status}>"
