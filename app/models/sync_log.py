import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class SyncLog(Base):
    """Log entry for an integration sync operation."""
    __tablename__ = "sync_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_id = Column(UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False)

    # "running" | "success" | "partial" | "failed"
    status = Column(String(20), nullable=False)

    # "manual" | "scheduled"
    trigger_type = Column(String(20), nullable=False, default="manual")
    triggered_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    rows_fetched = Column(Integer, nullable=False, default=0)
    rows_written = Column(Integer, nullable=False, default=0)
    rows_skipped = Column(Integer, nullable=False, default=0)
    errors_count = Column(Integer, nullable=False, default=0)

    error_details = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)

    # Relationships
    integration = relationship("Integration", back_populates="sync_logs")
    triggered_by_user = relationship("User")

    __table_args__ = (
        Index("ix_sync_logs_integration_id", "integration_id"),
        Index("ix_sync_logs_started_at", "started_at"),
        Index("ix_sync_logs_status", "status"),
    )

    def __repr__(self):
        return f"<SyncLog {self.integration_id} {self.status} at {self.started_at}>"
