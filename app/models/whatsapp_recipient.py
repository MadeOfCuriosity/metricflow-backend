import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class WhatsAppRecipient(Base):
    """A person this org's WhatsApp Notifier app sends messages to. Managed
    inside the app itself (added by an admin), not derived from any core
    model — the app is generic: the same recipient list can be a customer
    getting a receivables reminder, a stakeholder getting a daily KPI
    report, or anything else the org configures the data source and
    template to mean. `notes` is free text the admin sets per recipient
    (e.g. an account reference or a personalized detail) and is available
    as a template variable at send time.
    """
    __tablename__ = "whatsapp_recipients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    phone = Column(String(32), nullable=False)  # E.164
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_whatsapp_recipients_org_id", "org_id"),
        Index("ix_whatsapp_recipients_org_phone", "org_id", "phone"),
    )

    def __repr__(self):
        return f"<WhatsAppRecipient {self.name} org={self.org_id}>"
