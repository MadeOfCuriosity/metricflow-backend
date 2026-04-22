import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Index

from app.core.database import Base
from sqlalchemy.dialects.postgresql import UUID


class SalesLead(Base):
    """Inbound contact-sales lead captured from the landing page."""

    __tablename__ = "sales_leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Submitted fields
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    company = Column(String(255), nullable=True)
    team_size = Column(String(50), nullable=True)  # e.g. "1-10", "11-50", "51-200", "200+"
    message = Column(Text, nullable=True)

    # Provenance
    source = Column(String(50), nullable=False, default="enterprise_contact")
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # Sales pipeline state
    # new | contacted | qualified | won | lost
    status = Column(String(20), nullable=False, default="new")
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_sales_leads_status", "status"),
        Index("ix_sales_leads_email", "email"),
    )

    def __repr__(self):
        return f"<SalesLead {self.email} {self.status}>"
