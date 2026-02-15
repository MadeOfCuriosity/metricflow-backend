import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class Threshold(Base):
    __tablename__ = "thresholds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kpi_id = Column(UUID(as_uuid=True), ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False)
    threshold_type = Column(String(50), nullable=False)  # "fixed", "percentile", "std_dev"
    params = Column(JSONB, nullable=False)  # e.g., {"min": 100, "max": 500} or {"std_devs": 1.5}
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    kpi_definition = relationship("KPIDefinition", back_populates="thresholds")

    __table_args__ = (
        Index("ix_thresholds_kpi_id", "kpi_id"),
    )

    def __repr__(self):
        return f"<Threshold {self.threshold_type} for KPI {self.kpi_id}>"
