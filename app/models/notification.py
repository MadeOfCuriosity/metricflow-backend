import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.database import Base


class NotificationCampaign(Base):
    """A platform-wide announcement composed by a super-administrator."""

    __tablename__ = "notification_campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by_superadmin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("superadmins.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_email = Column(String(255), nullable=False)

    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    cta_label = Column(String(100), nullable=True)
    cta_url = Column(String(512), nullable=True)

    # in_app | email
    channel = Column(String(20), nullable=False, default="in_app")
    # info | warning | success | announcement
    severity = Column(String(20), nullable=False, default="info")
    # draft | sent | cancelled
    status = Column(String(20), nullable=False, default="draft")

    target_filter = Column(JSONB, nullable=True)
    recipient_org_count = Column(Integer, nullable=True)
    recipient_user_count = Column(Integer, nullable=True)

    sent_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<NotificationCampaign {self.title!r} {self.status}>"


class NotificationCampaignOrg(Base):
    __tablename__ = "notification_campaign_orgs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("notification_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("campaign_id", "org_id", name="uq_campaign_org"),)


class NotificationDismissal(Base):
    __tablename__ = "notification_dismissals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(
        UUID(as_uuid=True),
        ForeignKey("notification_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    dismissed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "campaign_id", name="uq_dismissal_user_campaign"),
    )
