import uuid
from datetime import datetime

from sqlalchemy import Column, Date, Float, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class DataEntry(Base):
    __tablename__ = "data_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    kpi_id = Column(UUID(as_uuid=True), ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    date = Column(Date, nullable=False)
    values = Column(JSONB, nullable=False)  # e.g., {"revenue": 50000, "deals_closed": 10}
    calculated_value = Column(Float, nullable=False)  # the computed KPI result
    entered_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="data_entries")
    kpi_definition = relationship("KPIDefinition", back_populates="data_entries")
    room = relationship("Room", back_populates="data_entries")
    entered_by_user = relationship("User", back_populates="data_entries")

    # Unique constraints managed by partial indexes in migration 010:
    # - (org_id, kpi_id, date, room_id) WHERE room_id IS NOT NULL
    # - (org_id, kpi_id, date) WHERE room_id IS NULL
    __table_args__ = (
        Index("ix_data_entries_org_id", "org_id"),
        Index("ix_data_entries_kpi_id", "kpi_id"),
        Index("ix_data_entries_date", "date"),
        Index("ix_data_entries_org_kpi_date", "org_id", "kpi_id", "date"),
    )

    def __repr__(self):
        return f"<DataEntry {self.kpi_id} on {self.date}>"
