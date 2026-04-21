from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Organization,
    User,
    Subscription,
    Integration,
    KPIDefinition,
    DataEntry,
    NotificationCampaign,
    NotificationCampaignOrg,
    NotificationDismissal,
    SyncLog,
    WebhookEvent,
    AIUsage,
)


ACTIVE_STATUSES = ("active", "authenticated", "trialing")


def _apply_target_filter(query, target: dict):
    """Apply campaign target filter to an Organization query."""
    if target.get("all"):
        return query
    industries = target.get("industries")
    plan_codes = target.get("plan_codes")
    plan_statuses = target.get("plan_statuses")
    if industries:
        query = query.filter(Organization.industry.in_(industries))
    if plan_codes:
        query = query.filter(Organization.plan_code.in_(plan_codes))
    if plan_statuses:
        query = query.filter(Organization.plan_status.in_(plan_statuses))
    return query


class CampaignService:
    @staticmethod
    def preview(db: Session, target: dict) -> tuple[int, int]:
        """Return (org_count, user_count) that match the target filter."""
        org_q = _apply_target_filter(db.query(Organization.id), target)
        org_ids = [r[0] for r in org_q.all()]
        if not org_ids:
            return 0, 0
        user_count = (
            db.query(func.count(User.id)).filter(User.org_id.in_(org_ids)).scalar() or 0
        )
        return len(org_ids), user_count

    @staticmethod
    def send(db: Session, campaign: NotificationCampaign) -> None:
        """Snapshot target orgs, mark campaign as sent, compute counts.

        Email channel is not wired to a provider yet — we still mark as sent so
        the campaign is recorded, but no email is dispatched.
        """
        target = campaign.target_filter or {}
        org_q = _apply_target_filter(db.query(Organization.id), target)
        org_ids = [r[0] for r in org_q.all()]

        # Snapshot recipient orgs so later org/filter changes don't alter history
        for org_id in org_ids:
            db.add(
                NotificationCampaignOrg(campaign_id=campaign.id, org_id=org_id)
            )

        user_count = (
            db.query(func.count(User.id)).filter(User.org_id.in_(org_ids)).scalar() or 0
            if org_ids
            else 0
        )
        campaign.recipient_org_count = len(org_ids)
        campaign.recipient_user_count = user_count
        campaign.status = "sent"
        campaign.sent_at = datetime.utcnow()
        db.commit()
        db.refresh(campaign)


class InboxService:
    """Serves in-app notification banners to org users."""

    @staticmethod
    def get_active_for_user(db: Session, user: User) -> list[NotificationCampaign]:
        now = datetime.utcnow()
        dismissed_subq = (
            db.query(NotificationDismissal.campaign_id)
            .filter(NotificationDismissal.user_id == user.id)
            .subquery()
        )
        q = (
            db.query(NotificationCampaign)
            .join(
                NotificationCampaignOrg,
                NotificationCampaignOrg.campaign_id == NotificationCampaign.id,
            )
            .filter(
                NotificationCampaign.status == "sent",
                NotificationCampaign.channel == "in_app",
                NotificationCampaignOrg.org_id == user.org_id,
                or_(
                    NotificationCampaign.expires_at.is_(None),
                    NotificationCampaign.expires_at > now,
                ),
                ~NotificationCampaign.id.in_(dismissed_subq),
            )
            .order_by(NotificationCampaign.sent_at.desc())
        )
        return q.all()

    @staticmethod
    def dismiss(db: Session, user: User, campaign_id: UUID) -> None:
        existing = (
            db.query(NotificationDismissal)
            .filter(
                NotificationDismissal.user_id == user.id,
                NotificationDismissal.campaign_id == campaign_id,
            )
            .first()
        )
        if existing:
            return
        db.add(NotificationDismissal(user_id=user.id, campaign_id=campaign_id))
        db.commit()


class IndustryInsightsService:
    @staticmethod
    def get_breakdown(db: Session) -> list[dict]:
        price_map = settings.razorpay_plan_prices()
        rows = (
            db.query(Organization.industry, Organization.id, Organization.plan_code, Organization.plan_status)
            .all()
        )
        # Group orgs by industry bucket
        buckets: dict[str, dict] = {}
        for industry, org_id, plan_code, plan_status in rows:
            key = industry or "Unspecified"
            b = buckets.setdefault(
                key,
                {
                    "industry": key,
                    "org_ids": [],
                    "active_plan_counts": {},
                },
            )
            b["org_ids"].append(org_id)
            if plan_status in ACTIVE_STATUSES and plan_code:
                b["active_plan_counts"][plan_code] = (
                    b["active_plan_counts"].get(plan_code, 0) + 1
                )

        out = []
        for key, b in buckets.items():
            org_ids = b["org_ids"]
            user_count = (
                db.query(func.count(User.id))
                .filter(User.org_id.in_(org_ids))
                .scalar()
                or 0
            ) if org_ids else 0
            active_subs = (
                db.query(func.count(Subscription.id))
                .filter(
                    Subscription.org_id.in_(org_ids),
                    Subscription.status.in_(ACTIVE_STATUSES),
                )
                .scalar()
                or 0
            ) if org_ids else 0
            with_integrations = (
                db.query(func.count(func.distinct(Integration.org_id)))
                .filter(Integration.org_id.in_(org_ids))
                .scalar()
                or 0
            ) if org_ids else 0
            with_kpis = (
                db.query(func.count(func.distinct(KPIDefinition.org_id)))
                .filter(KPIDefinition.org_id.in_(org_ids))
                .scalar()
                or 0
            ) if org_ids else 0
            with_data = (
                db.query(func.count(func.distinct(DataEntry.org_id)))
                .filter(DataEntry.org_id.in_(org_ids))
                .scalar()
                or 0
            ) if org_ids else 0
            mrr = 0.0
            for code, count in b["active_plan_counts"].items():
                mrr += price_map.get(code, 0.0) * count

            out.append(
                {
                    "industry": key,
                    "org_count": len(org_ids),
                    "user_count": user_count,
                    "active_subscriptions": active_subs,
                    "orgs_with_integrations": with_integrations,
                    "orgs_with_kpis": with_kpis,
                    "orgs_with_data": with_data,
                    "mrr": round(mrr, 2),
                }
            )

        out.sort(key=lambda r: r["org_count"], reverse=True)
        return out


class SystemHealthService:
    @staticmethod
    def get_health(db: Session) -> dict:
        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # Integration failures (current state)
        broken_rows = (
            db.query(Integration, Organization.name)
            .join(Organization, Integration.org_id == Organization.id)
            .filter(Integration.status.in_(("error", "disconnected")))
            .order_by(Integration.created_at.desc())
            .limit(50)
            .all()
        )
        # Last sync timestamp per broken integration (if any)
        integration_failures = []
        for integ, org_name in broken_rows:
            last_sync = (
                db.query(func.max(SyncLog.started_at))
                .filter(SyncLog.integration_id == integ.id)
                .scalar()
            )
            integration_failures.append(
                {
                    "org_id": integ.org_id,
                    "org_name": org_name,
                    "provider": integ.provider,
                    "status": integ.status,
                    "error_message": integ.error_message,
                    "last_sync_at": last_sync,
                }
            )

        # Webhook activity (last 7 days)
        total_events_7d = (
            db.query(func.count(WebhookEvent.id))
            .filter(WebhookEvent.received_at >= seven_days_ago)
            .scalar()
            or 0
        )
        last_event_at = db.query(func.max(WebhookEvent.received_at)).scalar()

        # Sync failures (last 7 days)
        total_syncs_7d = (
            db.query(func.count(SyncLog.id))
            .filter(SyncLog.started_at >= seven_days_ago)
            .scalar()
            or 0
        )
        failed_syncs_7d = (
            db.query(func.count(SyncLog.id))
            .filter(
                SyncLog.started_at >= seven_days_ago,
                SyncLog.status == "failed",
            )
            .scalar()
            or 0
        )
        last_sync_at = db.query(func.max(SyncLog.started_at)).scalar()

        # AI usage (last 30 days)
        calls_30d = (
            db.query(func.coalesce(func.sum(AIUsage.call_count), 0))
            .filter(AIUsage.usage_date >= thirty_days_ago.date())
            .scalar()
            or 0
        )
        orgs_using_ai_30d = (
            db.query(func.count(func.distinct(AIUsage.org_id)))
            .filter(
                AIUsage.usage_date >= thirty_days_ago.date(),
                AIUsage.call_count > 0,
            )
            .scalar()
            or 0
        )

        return {
            "integration_failures": integration_failures,
            "webhooks": {
                "total_events_7d": total_events_7d,
                "failed_events_7d": 0,  # webhook_events table doesn't track failure status
                "last_event_at": last_event_at,
            },
            "syncs": {
                "total_syncs_7d": total_syncs_7d,
                "failed_syncs_7d": failed_syncs_7d,
                "last_sync_at": last_sync_at,
            },
            "ai_usage": {
                "calls_30d": int(calls_30d),
                "orgs_using_ai_30d": int(orgs_using_ai_30d),
            },
        }
