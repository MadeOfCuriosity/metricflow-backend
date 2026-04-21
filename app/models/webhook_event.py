import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class WebhookEvent(Base):
    """Idempotency log for external webhooks (Razorpay, etc.)."""

    __tablename__ = "webhook_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(String(50), nullable=False)
    event_id = Column(String(255), nullable=False)
    event_type = Column(String(100), nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_webhook_events_provider_event_id"),
        Index("ix_webhook_events_received_at", "received_at"),
    )
