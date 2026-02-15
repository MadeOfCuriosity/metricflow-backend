"""Token blacklist model for invalidated tokens."""

from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class TokenBlacklist(Base):
    """Stores blacklisted/revoked JWT tokens."""

    __tablename__ = "token_blacklist"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    jti = Column(String(36), unique=True, nullable=False, index=True)  # JWT ID
    token_type = Column(String(20), nullable=False)  # 'access' or 'refresh'
    user_id = Column(UUID(as_uuid=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    blacklisted_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Index for cleanup of expired tokens
    __table_args__ = (
        Index("ix_token_blacklist_expires_at", "expires_at"),
    )


class RefreshToken(Base):
    """Stores active refresh tokens for rotation."""

    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)  # SHA-256 hash
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    rotated_at = Column(DateTime(timezone=True), nullable=True)
    is_revoked = Column(String(1), default="N")  # 'Y' or 'N'

    __table_args__ = (
        Index("ix_refresh_tokens_user_id_revoked", "user_id", "is_revoked"),
    )
