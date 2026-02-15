import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint, Index, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class IntegrationFieldMapping(Base):
    """Maps an external field/column to a MetricFlow DataField."""
    __tablename__ = "integration_field_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_id = Column(UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False)
    data_field_id = Column(UUID(as_uuid=True), ForeignKey("data_fields.id", ondelete="CASCADE"), nullable=False)

    # External source field identification
    external_field_name = Column(String(500), nullable=False)
    external_field_label = Column(String(500), nullable=True)

    # Aggregation: "direct" | "count" | "sum" | "avg" | "min" | "max"
    aggregation = Column(String(20), nullable=False, default="direct")

    # Optional filter for CRM connectors (e.g., {"Stage": "Closed Won"})
    filter_criteria = Column(JSON, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    integration = relationship("Integration", back_populates="field_mappings")
    data_field = relationship("DataField")

    __table_args__ = (
        UniqueConstraint("integration_id", "external_field_name", "data_field_id", name="uq_mapping_integration_ext_field"),
        Index("ix_field_mappings_integration_id", "integration_id"),
        Index("ix_field_mappings_data_field_id", "data_field_id"),
    )

    def __repr__(self):
        return f"<IntegrationFieldMapping {self.external_field_name} -> DataField {self.data_field_id}>"
