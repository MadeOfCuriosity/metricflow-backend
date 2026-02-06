import uuid
from datetime import datetime, date

from sqlalchemy import Column, String, Date, Integer, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class AIUsage(Base):
    """Track AI API usage per organization for rate limiting."""
    __tablename__ = "ai_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    usage_date = Column(Date, nullable=False, default=date.today)
    call_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", backref="ai_usage")

    __table_args__ = (
        Index("ix_ai_usage_org_date", "org_id", "usage_date", unique=True),
    )

    def __repr__(self):
        return f"<AIUsage org={self.org_id} date={self.usage_date} calls={self.call_count}>"
