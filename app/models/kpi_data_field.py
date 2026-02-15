import uuid

from sqlalchemy import Column, String, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class KPIDataField(Base):
    """Join table linking KPI definitions to their required data fields."""
    __tablename__ = "kpi_data_fields"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kpi_id = Column(UUID(as_uuid=True), ForeignKey("kpi_definitions.id", ondelete="CASCADE"), nullable=False)
    data_field_id = Column(UUID(as_uuid=True), ForeignKey("data_fields.id", ondelete="CASCADE"), nullable=False)
    variable_name = Column(String(255), nullable=False)  # The variable name used in the KPI formula

    # Relationships
    kpi_definition = relationship("KPIDefinition", back_populates="kpi_data_fields")
    data_field = relationship("DataField", back_populates="kpi_data_fields")

    __table_args__ = (
        UniqueConstraint("kpi_id", "data_field_id", name="uq_kpi_data_field"),
        Index("ix_kpi_data_fields_kpi_id", "kpi_id"),
        Index("ix_kpi_data_fields_data_field_id", "data_field_id"),
    )

    def __repr__(self):
        return f"<KPIDataField kpi={self.kpi_id} field={self.data_field_id} var={self.variable_name}>"
