import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.database import Base


class SuperAdminAuditLog(Base):
    __tablename__ = "superadmin_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    superadmin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("superadmins.id", ondelete="SET NULL"),
        nullable=True,
    )
    superadmin_email = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=True)
    target_id = Column(String(100), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<AuditLog {self.action} by {self.superadmin_email}>"
