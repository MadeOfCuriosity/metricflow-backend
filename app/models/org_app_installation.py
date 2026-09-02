import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, Text, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class OrgAppInstallation(Base):
    """An org's installation of a first-party app: install/enable state,
    entitlement, and config. Every query against this table filters on org_id."""
    __tablename__ = "org_app_installations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)

    # Key into app/services/apps.APP_REGISTRY — no FK, apps aren't a DB table.
    app_key = Column(String(100), nullable=False)

    is_enabled = Column(Boolean, nullable=False, default=False)

    # "not_required" | "required" | "granted" | "revoked"
    entitlement_status = Column(String(20), nullable=False, default="not_required")

    # Plain, non-secret config shaped by the app's declared config_schema.
    config = Column(JSONB, nullable=False, default=dict)

    # Reserved for Fernet-encrypted secret config. Stored separately from
    # `config` at the schema level (a single encrypted-blob Text column, same
    # shape as Integration.access_token_encrypted etc.) so that when secret
    # config is needed, the service layer can start calling
    # app.core.encryption.encrypt_value/decrypt_value on this column with zero
    # data migration. Unused and always NULL today — no Fernet plumbing yet.
    secret_config_encrypted = Column(Text, nullable=True)

    installed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    installed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization", back_populates="app_installations")
    installed_by_user = relationship("User")
    run_records = relationship(
        "AppRunRecord", back_populates="installation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_org_app_installations_org_id", "org_id"),
        Index("ix_org_app_installations_app_key", "app_key"),
        UniqueConstraint("org_id", "app_key", name="uq_org_app_installations_org_app"),
    )

    def __repr__(self):
        return f"<OrgAppInstallation {self.app_key} org={self.org_id} enabled={self.is_enabled}>"
