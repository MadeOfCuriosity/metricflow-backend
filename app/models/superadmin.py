import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class SuperAdmin(Base):
    __tablename__ = "superadmins"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    google_id = Column(String(255), nullable=True, index=True)
    picture = Column(String(512), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by_email = Column(String(255), nullable=True)

    def __repr__(self):
        return f"<SuperAdmin {self.email}>"
