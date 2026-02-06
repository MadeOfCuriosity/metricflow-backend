import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserRoomAssignment(Base):
    """
    Maps users (specifically room_admin role) to rooms they have access to.
    Admins have access to all rooms, so they don't need entries here.
    """
    __tablename__ = "user_room_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="room_assignments")
    room = relationship("Room", back_populates="user_assignments")
    assigned_by_user = relationship("User", foreign_keys=[assigned_by])

    # Constraints
    __table_args__ = (
        UniqueConstraint("user_id", "room_id", name="uq_user_room_assignment"),
        Index("ix_user_room_assignments_user_id", "user_id"),
        Index("ix_user_room_assignments_room_id", "room_id"),
    )

    def __repr__(self):
        return f"<UserRoomAssignment user={self.user_id} room={self.room_id}>"
