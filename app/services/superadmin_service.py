from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import func, cast, Date
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_superadmin_token, verify_google_id_token
from app.models import (
    SuperAdmin,
    Organization,
    User,
    Subscription,
    Room,
    Integration,
    KPIDefinition,
    DataEntry,
)


ACTIVE_STATUSES = ("active", "authenticated", "trialing")


class SuperAdminAuthService:
    @staticmethod
    def login_with_google(db: Session, credential: str) -> Optional[tuple[SuperAdmin, str]]:
        """Verify Google credential, match to superadmin allow-list, issue token."""
        info = verify_google_id_token(credential, settings.GOOGLE_OAUTH_CLIENT_ID)
        if info is None:
            return None

        email = (info.get("email") or "").lower().strip()
        if not email:
            return None

        admin = (
            db.query(SuperAdmin)
            .filter(func.lower(SuperAdmin.email) == email)
            .first()
        )
        if admin is None or not admin.is_active:
            return None

        # Backfill profile info from Google on every login
        admin.google_id = info.get("sub") or admin.google_id
        admin.name = info.get("name") or admin.name
        admin.picture = info.get("picture") or admin.picture
        admin.last_login_at = datetime.utcnow()
        db.commit()
        db.refresh(admin)

        token = create_superadmin_token(str(admin.id), admin.email)
        return admin, token


class PlatformInsightsService:
    @staticmethod
    def get_insights(db: Session) -> dict:
        now = datetime.utcnow()
        thirty_days_ago = now - timedelta(days=30)

        total_orgs = db.query(func.count(Organization.id)).scalar() or 0
        total_users = db.query(func.count(User.id)).scalar() or 0

        active_subs_q = db.query(Subscription).filter(
            Subscription.status.in_(ACTIVE_STATUSES)
        )
        active_subscriptions = active_subs_q.count()

        # MRR from configured price map
        price_map = settings.razorpay_plan_prices()
        mrr = 0.0
        if price_map:
            rows = (
                db.query(Subscription.plan_code, func.count(Subscription.id))
                .filter(Subscription.status.in_(ACTIVE_STATUSES))
                .group_by(Subscription.plan_code)
                .all()
            )
            for plan_code, count in rows:
                mrr += price_map.get(plan_code, 0.0) * count

        orgs_created_30d = (
            db.query(func.count(Organization.id))
            .filter(Organization.created_at >= thirty_days_ago)
            .scalar()
            or 0
        )
        users_created_30d = (
            db.query(func.count(User.id))
            .filter(User.created_at >= thirty_days_ago)
            .scalar()
            or 0
        )

        # Daily signup timeline (last 30 days)
        org_daily = (
            db.query(
                cast(Organization.created_at, Date).label("day"),
                func.count(Organization.id),
            )
            .filter(Organization.created_at >= thirty_days_ago)
            .group_by("day")
            .all()
        )
        user_daily = (
            db.query(
                cast(User.created_at, Date).label("day"),
                func.count(User.id),
            )
            .filter(User.created_at >= thirty_days_ago)
            .group_by("day")
            .all()
        )
        org_by_day = {d.isoformat(): c for d, c in org_daily}
        user_by_day = {d.isoformat(): c for d, c in user_daily}
        all_days = sorted(set(org_by_day) | set(user_by_day))
        signups_by_day = [
            {
                "date": d,
                "orgs": org_by_day.get(d, 0),
                "users": user_by_day.get(d, 0),
            }
            for d in all_days
        ]

        industry_rows = (
            db.query(Organization.industry, func.count(Organization.id))
            .group_by(Organization.industry)
            .all()
        )
        orgs_by_industry = [
            {"industry": (i or "Unspecified"), "count": c}
            for i, c in industry_rows
        ]

        plan_rows = (
            db.query(Organization.plan_code, func.count(Organization.id))
            .group_by(Organization.plan_code)
            .all()
        )
        orgs_by_plan = [
            {"plan_code": (p or "none"), "count": c} for p, c in plan_rows
        ]

        status_rows = (
            db.query(Organization.plan_status, func.count(Organization.id))
            .group_by(Organization.plan_status)
            .all()
        )
        orgs_by_plan_status = [
            {"plan_status": (s or "none"), "count": c} for s, c in status_rows
        ]

        with_integrations = (
            db.query(func.count(func.distinct(Integration.org_id))).scalar() or 0
        )
        with_kpis = (
            db.query(func.count(func.distinct(KPIDefinition.org_id))).scalar() or 0
        )
        with_rooms = db.query(func.count(func.distinct(Room.org_id))).scalar() or 0
        with_data = (
            db.query(func.count(func.distinct(DataEntry.org_id))).scalar() or 0
        )

        return {
            "total_orgs": total_orgs,
            "total_users": total_users,
            "active_subscriptions": active_subscriptions,
            "mrr": round(mrr, 2),
            "orgs_created_30d": orgs_created_30d,
            "users_created_30d": users_created_30d,
            "signups_by_day": signups_by_day,
            "orgs_by_industry": orgs_by_industry,
            "orgs_by_plan": orgs_by_plan,
            "orgs_by_plan_status": orgs_by_plan_status,
            "feature_adoption": {
                "with_integrations": with_integrations,
                "with_kpis": with_kpis,
                "with_rooms": with_rooms,
                "with_data": with_data,
            },
        }
