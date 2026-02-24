import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class DataFieldRoom(Base):
    """Join table for assigning data fields to rooms (many-to-many)."""
    __tablename__ = "data_field_rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    data_field_id = Column(UUID(as_uuid=True), ForeignKey("data_fields.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    data_field = relationship("DataField", back_populates="room_assignments")
    room = relationship("Room", back_populates="data_field_assignments")

    __table_args__ = (
        Index("ix_data_field_rooms_data_field_id", "data_field_id"),
        Index("ix_data_field_rooms_room_id", "room_id"),
        UniqueConstraint("data_field_id", "room_id", name="uq_data_field_room"),
    )

    def __repr__(self):
        return f"<DataFieldRoom field={self.data_field_id} room={self.room_id}>"
