"""Razorpay subscription routes."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin_org
from app.core.config import settings
from app.core.rate_limit import limiter, public_limiter
from app.models import Organization, Subscription, User
from app.schemas.subscriptions import (
    CreateSubscriptionRequest,
    CreateSubscriptionResponse,
    PlanListResponse,
    PlanResponse,
    SubscriptionResponse,
    VerifySubscriptionRequest,
)
from app.services.razorpay_service import RazorpayConfigError, RazorpayService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


def _to_response(sub: Subscription) -> SubscriptionResponse:
    return SubscriptionResponse.model_validate(sub)


@router.get("/plans", response_model=PlanListResponse)
def list_plans(
    _admin_org: tuple[User, Organization] = Depends(require_admin_org),
):
    """List configured Razorpay plans."""
    plans = RazorpayService.list_plans()
    return PlanListResponse(plans=[PlanResponse(**p) for p in plans])


@router.get("/current", response_model=SubscriptionResponse | None)
def get_current_subscription(
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Return the most recent subscription for the current org, if any."""
    _, org = admin_org
    sub = (
        db.query(Subscription)
        .filter(Subscription.org_id == org.id)
        .order_by(Subscription.created_at.desc())
        .first()
    )
    return _to_response(sub) if sub else None


@router.post(
    "/create",
    response_model=CreateSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
def create_subscription(
    request: Request,
    data: CreateSubscriptionRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Create a Razorpay subscription. The frontend then opens checkout with the returned id."""
    _, org = admin_org
    try:
        sub = RazorpayService.create_subscription(
            db=db,
            org_id=org.id,
            plan_code=data.plan_code,
            total_count=data.total_count,
        )
    except RazorpayConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Failed to create Razorpay subscription")
        raise HTTPException(status_code=502, detail="Payment provider error. Please try again.")

    return CreateSubscriptionResponse(
        subscription_id=sub.razorpay_subscription_id,
        razorpay_key_id=settings.RAZORPAY_KEY_ID or "",
        plan_code=sub.plan_code,
        short_url=getattr(sub, "short_url", None),
    )


@router.post("/verify", response_model=SubscriptionResponse)
@limiter.limit("10/minute")
def verify_subscription(
    request: Request,
    data: VerifySubscriptionRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Verify the post-checkout signature and refresh local state."""
    _, org = admin_org

    sub = (
        db.query(Subscription)
        .filter(
            Subscription.org_id == org.id,
            Subscription.razorpay_subscription_id == data.razorpay_subscription_id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    ok = RazorpayService.verify_payment_signature(
        razorpay_subscription_id=data.razorpay_subscription_id,
        razorpay_payment_id=data.razorpay_payment_id,
        razorpay_signature=data.razorpay_signature,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    try:
        sub = RazorpayService.sync_from_razorpay(db, sub)
    except Exception:
        logger.exception("Failed to sync subscription after verify")

    return _to_response(sub)


@router.post("/{subscription_id}/cancel", response_model=SubscriptionResponse)
def cancel_subscription(
    subscription_id: str,
    cancel_at_cycle_end: bool = True,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Cancel a subscription. Defaults to cancelling at the end of the current cycle."""
    _, org = admin_org

    sub = (
        db.query(Subscription)
        .filter(
            Subscription.org_id == org.id,
            Subscription.razorpay_subscription_id == subscription_id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    try:
        RazorpayService.cancel_subscription(
            subscription_id, cancel_at_cycle_end=cancel_at_cycle_end
        )
        sub = RazorpayService.sync_from_razorpay(db, sub)
    except RazorpayConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception:
        logger.exception("Failed to cancel subscription")
        raise HTTPException(status_code=502, detail="Payment provider error. Please try again.")

    return _to_response(sub)


@router.post("/webhook", status_code=200)
@public_limiter.limit("600/minute")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """Razorpay webhook endpoint. Public — verified via signature header."""
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not RazorpayService.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        event = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Idempotency check — Razorpay retries events; drop duplicates silently
    event_id = event.get("id") or request.headers.get("X-Razorpay-Event-Id", "")
    if event_id:
        from app.models import WebhookEvent
        existing = db.query(WebhookEvent).filter(
            WebhookEvent.provider == "razorpay",
            WebhookEvent.event_id == event_id,
        ).first()
        if existing:
            logger.info(f"Razorpay webhook {event_id} already processed, skipping")
            return {"status": "ok", "duplicate": True}
        db.add(WebhookEvent(provider="razorpay", event_id=event_id, event_type=event.get("event", "")))
        db.commit()

    try:
        RazorpayService.apply_webhook_event(db, event)
    except Exception:
        logger.exception("Failed to apply Razorpay webhook event")
        # Return 200 anyway so Razorpay doesn't keep retrying for unrecoverable errors;
        # change this to 500 if you want retries.

    return {"status": "ok"}
