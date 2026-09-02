import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class AppRunRecord(Base):
    """Durable source-of-truth record of one app execution attempt.

    org_id and app_key are denormalized from the installation (same
    fast-filtering rationale as SyncLog/DataEntry) so run history survives
    being queried without a join, even though they're also derivable via
    installation_id -> OrgAppInstallation.

    Idempotency: (installation_id, idempotency_key) is unique. A retried or
    duplicate-fired execution reuses the same key and the runner returns the
    existing record instead of re-executing the app — see AppRunner.execute.
    """
    __tablename__ = "app_run_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installation_id = Column(
        UUID(as_uuid=True), ForeignKey("org_app_installations.id", ondelete="CASCADE"), nullable=False
    )
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    app_key = Column(String(100), nullable=False)

    # "running" | "success" | "partial" | "failed"
    status = Column(String(20), nullable=False, default="running")

    # "on_demand" | "scheduled" | "event" (event is reserved/unused today)
    trigger_type = Column(String(20), nullable=False)
    triggered_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    idempotency_key = Column(String(150), nullable=False)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    result = Column(JSONB, nullable=True)  # the app's AppRunResult.data payload
    error = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)

    # Relationships
    installation = relationship("OrgAppInstallation", back_populates="run_records")
    organization = relationship("Organization")
    triggered_by_user = relationship("User")

    __table_args__ = (
        Index("ix_app_run_records_installation_id", "installation_id"),
        Index("ix_app_run_records_org_id", "org_id"),
        Index("ix_app_run_records_started_at", "started_at"),
        Index("ix_app_run_records_status", "status"),
        UniqueConstraint(
            "installation_id", "idempotency_key", name="uq_app_run_records_installation_idempotency"
        ),
    )

    def __repr__(self):
        return f"<AppRunRecord {self.app_key} org={self.org_id} {self.status}>"
