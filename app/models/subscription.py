import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Subscription(Base):
    """Razorpay subscription record for an organization."""

    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Plan info
    plan_code = Column(String(50), nullable=False)  # e.g. "starter", "pro"
    razorpay_plan_id = Column(String(100), nullable=False)
    razorpay_subscription_id = Column(String(100), nullable=False, unique=True)
    razorpay_customer_id = Column(String(100), nullable=True)

    # Lifecycle
    # created | authenticated | active | pending | halted | cancelled | completed | expired
    status = Column(String(30), nullable=False, default="created")
    total_count = Column(Integer, nullable=True)  # number of billing cycles
    paid_count = Column(Integer, nullable=False, default=0)

    current_start = Column(DateTime, nullable=True)
    current_end = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    organization = relationship("Organization", back_populates="subscriptions")

    __table_args__ = (
        Index("ix_subscriptions_org_id", "org_id"),
        Index("ix_subscriptions_status", "status"),
    )

    def __repr__(self):
        return f"<Subscription {self.razorpay_subscription_id} {self.status}>"
