import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class Integration(Base):
    """External data source integration (Google Sheets, Zoho CRM, LeadSquared)."""
    __tablename__ = "integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Provider: "google_sheets" | "zoho_crm" | "leadsquared"
    provider = Column(String(50), nullable=False)
    display_name = Column(String(255), nullable=False)

    # Status: "pending_auth" | "connected" | "error" | "disconnected"
    status = Column(String(30), nullable=False, default="pending_auth")
    error_message = Column(Text, nullable=True)

    # Provider-specific config (sheet_id, module name, etc.)
    config = Column(JSON, nullable=True, default=dict)

    # OAuth tokens (Fernet-encrypted)
    access_token_encrypted = Column(Text, nullable=True)
    refresh_token_encrypted = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)

    # API key auth (for LeadSquared, Fernet-encrypted)
    api_key_encrypted = Column(Text, nullable=True)
    api_secret_encrypted = Column(Text, nullable=True)

    # Sync schedule: "manual" | "1h" | "6h" | "12h" | "24h"
    sync_schedule = Column(String(20), nullable=False, default="manual")
    last_synced_at = Column(DateTime, nullable=True)
    next_sync_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="integrations")
    created_by_user = relationship("User")
    field_mappings = relationship("IntegrationFieldMapping", back_populates="integration", cascade="all, delete-orphan")
    sync_logs = relationship("SyncLog", back_populates="integration", cascade="all, delete-orphan", order_by="desc(SyncLog.started_at)")

    __table_args__ = (
        Index("ix_integrations_org_id", "org_id"),
        Index("ix_integrations_provider", "provider"),
        Index("ix_integrations_status", "status"),
        Index("ix_integrations_next_sync", "next_sync_at"),
    )

    def __repr__(self):
        return f"<Integration {self.provider}: {self.display_name} ({self.status})>"
