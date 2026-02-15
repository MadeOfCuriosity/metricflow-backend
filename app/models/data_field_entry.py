import uuid
from datetime import datetime

from sqlalchemy import Column, Date, Float, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class DataFieldEntry(Base):
    """Raw per-field per-date value entry. One value per data field per date."""
    __tablename__ = "data_field_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    data_field_id = Column(UUID(as_uuid=True), ForeignKey("data_fields.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    value = Column(Float, nullable=False)
    entered_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="data_field_entries")
    data_field = relationship("DataField", back_populates="field_entries")
    entered_by_user = relationship("User", back_populates="data_field_entries")

    __table_args__ = (
        UniqueConstraint("org_id", "data_field_id", "date", name="uq_field_entry_org_field_date"),
        Index("ix_data_field_entries_org_id", "org_id"),
        Index("ix_data_field_entries_data_field_id", "data_field_id"),
        Index("ix_data_field_entries_date", "date"),
        Index("ix_data_field_entries_org_field_date", "org_id", "data_field_id", "date"),
    )

    def __repr__(self):
        return f"<DataFieldEntry {self.data_field_id} on {self.date}: {self.value}>"
