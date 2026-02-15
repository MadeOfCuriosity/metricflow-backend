import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Insight(Base):
    __tablename__ = "insights"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    kpi_id = Column(UUID(as_uuid=True), ForeignKey("kpi_definitions.id", ondelete="SET NULL"), nullable=True)
    insight_text = Column(Text, nullable=False)
    priority = Column(String(20), nullable=False)  # "low", "medium", "high"
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="insights")
    kpi_definition = relationship("KPIDefinition", back_populates="insights")

    __table_args__ = (
        Index("ix_insights_org_id", "org_id"),
        Index("ix_insights_kpi_id", "kpi_id"),
        Index("ix_insights_priority", "priority"),
        Index("ix_insights_generated_at", "generated_at"),
    )

    def __repr__(self):
        return f"<Insight {self.priority}: {self.insight_text[:50]}...>"
