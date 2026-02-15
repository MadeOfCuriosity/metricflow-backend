import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class RoomKPIAssignment(Base):
    """Join table for assigning KPIs to rooms."""
    __tablename__ = "room_kpi_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    kpi_id = Column(UUID(as_uuid=True), ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    room = relationship("Room", back_populates="kpi_assignments")
    kpi_definition = relationship("KPIDefinition", back_populates="room_assignments")
    assigned_by_user = relationship("User", back_populates="kpi_assignments")

    __table_args__ = (
        Index("ix_room_kpi_assignments_room_id", "room_id"),
        Index("ix_room_kpi_assignments_kpi_id", "kpi_id"),
        UniqueConstraint("room_id", "kpi_id", name="uq_room_kpi_assignment"),
    )

    def __repr__(self):
        return f"<RoomKPIAssignment room={self.room_id} kpi={self.kpi_id}>"
