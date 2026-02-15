import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)  # Nullable for Google-auth users
    name = Column(String(255), nullable=False)
    google_id = Column(String(255), nullable=True, index=True)
    auth_provider = Column(String(20), nullable=True, default="email")  # 'email', 'google', 'both'
    role = Column(String(20), nullable=False, default="admin")  # "admin" or "room_admin"
    role_label = Column(String(100), nullable=False)  # "Sales Head", "Marketing Head", etc.
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="users")
    kpi_definitions = relationship("KPIDefinition", back_populates="created_by_user")
    data_entries = relationship("DataEntry", back_populates="entered_by_user")
    created_rooms = relationship("Room", back_populates="created_by_user")
    kpi_assignments = relationship("RoomKPIAssignment", back_populates="assigned_by_user")
    room_assignments = relationship("UserRoomAssignment", foreign_keys="UserRoomAssignment.user_id", back_populates="user")
    data_fields = relationship("DataField", back_populates="created_by_user")
    data_field_entries = relationship("DataFieldEntry", back_populates="entered_by_user")

    # Constraints
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_user_org_email"),
        Index("ix_users_org_id", "org_id"),
        Index("ix_users_email", "email"),
    )

    def __repr__(self):
        return f"<User {self.email}>"
