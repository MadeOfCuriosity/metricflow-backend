import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class DataField(Base):
    """Reusable data field that can be referenced by multiple KPIs."""
    __tablename__ = "data_fields"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)  # Display name: "Revenue"
    variable_name = Column(String(255), nullable=False)  # Formula variable: "revenue" (org-unique, immutable)
    description = Column(Text, nullable=True)
    unit = Column(String(50), nullable=True)  # "$", "%", "hours", etc.
    entry_interval = Column(String(20), nullable=False, default="daily")  # "daily", "weekly", "monthly", "custom"
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="data_fields")
    room = relationship("Room", back_populates="data_fields")
    created_by_user = relationship("User", back_populates="data_fields")
    field_entries = relationship("DataFieldEntry", back_populates="data_field", cascade="all, delete-orphan")
    kpi_data_fields = relationship("KPIDataField", back_populates="data_field", cascade="all, delete-orphan")

    # Unique constraints managed by partial indexes in migration 010:
    # - (org_id, variable_name, room_id) WHERE room_id IS NOT NULL
    # - (org_id, variable_name) WHERE room_id IS NULL
    __table_args__ = (
        Index("ix_data_fields_org_id", "org_id"),
        Index("ix_data_fields_room_id", "room_id"),
    )

    def __repr__(self):
        return f"<DataField {self.name} ({self.variable_name})>"
