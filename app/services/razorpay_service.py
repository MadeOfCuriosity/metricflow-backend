"""Razorpay subscription service.

Wraps the razorpay python SDK and persists subscription state in our DB.
"""
import hmac
import hashlib
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import razorpay
from razorpay.errors import SignatureVerificationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Subscription

logger = logging.getLogger(__name__)


class RazorpayConfigError(Exception):
    """Razorpay credentials are not configured."""


class RazorpayService:
    @staticmethod
    def _client() -> razorpay.Client:
        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise RazorpayConfigError(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set"
            )
        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        return client

    @staticmethod
    def get_plan_id(plan_code: str) -> str:
        plan_map = settings.razorpay_plan_map()
        if plan_code not in plan_map:
            raise ValueError(f"Unknown plan_code: {plan_code}")
        return plan_map[plan_code]

    @staticmethod
    def list_plans() -> list[dict[str, str]]:
        plan_map = settings.razorpay_plan_map()
        return [
            {"code": code, "razorpay_plan_id": plan_id}
            for code, plan_id in plan_map.items()
        ]

    @classmethod
    def create_subscription(
        cls,
        db: Session,
        org_id: UUID,
        plan_code: str,
        total_count: int,
    ) -> Subscription:
        """Create a Razorpay subscription and persist a record."""
        client = cls._client()
        plan_id = cls.get_plan_id(plan_code)

        razorpay_sub = client.subscription.create(
            {
                "plan_id": plan_id,
                "total_count": total_count,
                "customer_notify": 1,
                "notes": {"org_id": str(org_id)},
            }
        )

        sub = Subscription(
            org_id=org_id,
            plan_code=plan_code,
            razorpay_plan_id=plan_id,
            razorpay_subscription_id=razorpay_sub["id"],
            status=razorpay_sub.get("status", "created"),
            total_count=total_count,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)

        # Stash short_url on the model object for the route to read (not persisted)
        sub.short_url = razorpay_sub.get("short_url")  # type: ignore[attr-defined]
        return sub

    @classmethod
    def verify_payment_signature(
        cls,
        razorpay_subscription_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
    ) -> bool:
        """Verify the post-checkout signature returned by Razorpay Checkout."""
        client = cls._client()
        try:
            client.utility.verify_subscription_payment_signature(
                {
                    "razorpay_subscription_id": razorpay_subscription_id,
                    "razorpay_payment_id": razorpay_payment_id,
                    "razorpay_signature": razorpay_signature,
                }
            )
            return True
        except SignatureVerificationError:
            return False

    @classmethod
    def fetch_subscription(cls, subscription_id: str) -> dict[str, Any]:
        client = cls._client()
        return client.subscription.fetch(subscription_id)

    @classmethod
    def cancel_subscription(
        cls, subscription_id: str, cancel_at_cycle_end: bool = False
    ) -> dict[str, Any]:
        client = cls._client()
        return client.subscription.cancel(
            subscription_id, {"cancel_at_cycle_end": 1 if cancel_at_cycle_end else 0}
        )

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str) -> bool:
        secret = settings.RAZORPAY_WEBHOOK_SECRET
        if not secret:
            logger.error("RAZORPAY_WEBHOOK_SECRET not configured")
            return False
        expected = hmac.new(
            secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def _ts_to_dt(ts: Optional[int]) -> Optional[datetime]:
        if not ts:
            return None
        return datetime.utcfromtimestamp(ts)

    @classmethod
    def sync_from_razorpay(
        cls, db: Session, sub: Subscription
    ) -> Subscription:
        """Refresh local state from Razorpay's API."""
        data = cls.fetch_subscription(sub.razorpay_subscription_id)
        sub.status = data.get("status", sub.status)
        sub.paid_count = data.get("paid_count", sub.paid_count) or 0
        sub.total_count = data.get("total_count", sub.total_count)
        sub.current_start = cls._ts_to_dt(data.get("current_start"))
        sub.current_end = cls._ts_to_dt(data.get("current_end"))
        sub.ended_at = cls._ts_to_dt(data.get("ended_at"))
        if not sub.razorpay_customer_id and data.get("customer_id"):
            sub.razorpay_customer_id = data["customer_id"]
        db.commit()
        cls._mirror_to_organization(db, sub)
        db.refresh(sub)
        return sub

    @staticmethod
    def _mirror_to_organization(db: Session, sub: Subscription) -> None:
        """Mirror the subscription state onto the Organization for fast entitlement checks."""
        from app.models import Organization
        org = db.query(Organization).filter(Organization.id == sub.org_id).first()
        if not org:
            return
        # Only reflect active-ish states; terminal states clear the plan
        active_states = {"active", "authenticated", "trialing"}
        if sub.status in active_states:
            org.plan_code = sub.plan_code
            org.plan_status = sub.status
            org.plan_current_end = sub.current_end
        elif sub.status in {"cancelled", "completed", "expired", "halted"}:
            org.plan_code = None
            org.plan_status = sub.status
            org.plan_current_end = sub.current_end
        db.commit()

    @classmethod
    def apply_webhook_event(
        cls, db: Session, event: dict[str, Any]
    ) -> Optional[Subscription]:
        """Update local subscription from a webhook payload."""
        event_type = event.get("event", "")
        payload = event.get("payload", {}) or {}
        sub_entity = (payload.get("subscription") or {}).get("entity") or {}
        sub_id = sub_entity.get("id")
        if not sub_id:
            return None

        sub = (
            db.query(Subscription)
            .filter(Subscription.razorpay_subscription_id == sub_id)
            .first()
        )
        if not sub:
            logger.warning(f"Webhook for unknown subscription {sub_id}")
            return None

        sub.status = sub_entity.get("status", sub.status)
        sub.paid_count = sub_entity.get("paid_count", sub.paid_count) or 0
        sub.total_count = sub_entity.get("total_count", sub.total_count)
        sub.current_start = cls._ts_to_dt(sub_entity.get("current_start"))
        sub.current_end = cls._ts_to_dt(sub_entity.get("current_end"))
        sub.ended_at = cls._ts_to_dt(sub_entity.get("ended_at"))
        if sub_entity.get("customer_id"):
            sub.razorpay_customer_id = sub_entity["customer_id"]

        logger.info(f"Razorpay webhook {event_type} applied to {sub_id}")
        db.commit()
        cls._mirror_to_organization(db, sub)
        db.refresh(sub)
        return sub
