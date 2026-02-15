import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean, Index, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
import enum


from sqlalchemy.orm import relationship

from app.core.database import Base


class TimePeriod(str, enum.Enum):
    """Time period/frequency for KPI data collection."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    OTHER = "other"


class KPIDefinition(Base):
    __tablename__ = "kpi_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    formula = Column(String(500), nullable=False)  # e.g., "revenue / deals_closed"
    input_fields = Column(JSONB, nullable=False)  # e.g., ["revenue", "deals_closed"]
    category = Column(String(50), nullable=False)  # "Sales", "Marketing", "Operations", "Finance", "Custom"
    time_period = Column(
        Enum(TimePeriod, name="time_period_enum", create_constraint=True, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TimePeriod.DAILY
    )  # Frequency of data collection: daily, weekly, monthly, quarterly, other
    is_preset = Column(Boolean, default=False, nullable=False)
    is_shared = Column(Boolean, default=False, nullable=False)  # True = org-wide, visible in all rooms
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="kpi_definitions")
    created_by_user = relationship("User", back_populates="kpi_definitions")
    data_entries = relationship("DataEntry", back_populates="kpi_definition", cascade="all, delete-orphan")
    thresholds = relationship("Threshold", back_populates="kpi_definition", cascade="all, delete-orphan")
    insights = relationship("Insight", back_populates="kpi_definition")
    room_assignments = relationship("RoomKPIAssignment", back_populates="kpi_definition", cascade="all, delete-orphan")
    kpi_data_fields = relationship("KPIDataField", back_populates="kpi_definition", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_kpi_definitions_org_id", "org_id"),
        Index("ix_kpi_definitions_category", "category"),
        Index("ix_kpi_definitions_is_preset", "is_preset"),
    )

    def __repr__(self):
        return f"<KPIDefinition {self.name}>"
