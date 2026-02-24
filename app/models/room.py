import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class Room(Base):
    """Room model for organizing KPIs by department/section."""
    __tablename__ = "rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    parent_room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="rooms")
    parent_room = relationship("Room", remote_side=[id], back_populates="sub_rooms")
    sub_rooms = relationship("Room", back_populates="parent_room", cascade="all, delete-orphan")
    created_by_user = relationship("User", back_populates="created_rooms")
    kpi_assignments = relationship("RoomKPIAssignment", back_populates="room", cascade="all, delete-orphan")
    user_assignments = relationship("UserRoomAssignment", back_populates="room", cascade="all, delete-orphan")
    data_field_assignments = relationship("DataFieldRoom", back_populates="room", cascade="all, delete-orphan")
    data_entries = relationship("DataEntry", back_populates="room")

    __table_args__ = (
        Index("ix_rooms_org_id", "org_id"),
        Index("ix_rooms_parent_room_id", "parent_room_id"),
        UniqueConstraint("org_id", "name", "parent_room_id", name="uq_room_org_name_parent"),
    )

    def __repr__(self):
        return f"<Room {self.name}>"
