import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class WhatsAppSuppression(Base):
    """Org-scoped do-not-message list for the WhatsApp Receivables Reminder
    app. Every send checks this before messaging a number. v1 is manually
    maintained (admin adds numbers via the app UI); automated inbound-STOP
    capture via the org's WABA webhook is a fast-follow, not built here.
    """
    __tablename__ = "whatsapp_suppressions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)

    phone = Column(String(32), nullable=False)  # E.164
    reason = Column(String(255), nullable=True)  # "manual" | "customer_requested" | free text

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_whatsapp_suppressions_org_id", "org_id"),
        UniqueConstraint("org_id", "phone", name="uq_whatsapp_suppressions_org_phone"),
    )

    def __repr__(self):
        return f"<WhatsAppSuppression org={self.org_id} phone=***{self.phone[-4:] if self.phone else ''}>"
