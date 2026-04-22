from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_superadmin
from app.core.rate_limit import public_limiter
from app.core.security import (
    create_access_token,
    create_impersonation_token,
    create_refresh_token,
    store_refresh_token,
)
from app.models import (
    SuperAdmin,
    SuperAdminAuditLog,
    Organization,
    User,
    Subscription,
    Room,
    Integration,
    KPIDefinition,
    DataEntry,
    NotificationCampaign,
    SalesLead,
)
from app.schemas.sales_lead import (
    SalesLeadResponse,
    SalesLeadListResponse,
    SalesLeadUpdate,
)
from app.schemas.superadmin import (
    SuperAdminGoogleAuthRequest,
    SuperAdminAuthResponse,
    SuperAdminResponse,
    CreateSuperAdminRequest,
    UpdateSuperAdminRequest,
    PlatformInsightsResponse,
    OrgListResponse,
    OrgListItem,
    OrgDetailResponse,
    OrgDetailUser,
    OrgDetailSubscription,
    OrgDetailIntegration,
    GlobalUserListResponse,
    GlobalUserItem,
    GlobalSubscriptionListResponse,
    GlobalSubscriptionItem,
)
from app.schemas.superadmin_phase2 import (
    ImpersonationRequest,
    ImpersonationResponse,
    AuditLogItem,
    AuditLogListResponse,
    CampaignTargetPreviewRequest,
    CampaignTargetPreviewResponse,
    CreateCampaignRequest,
    CampaignResponse,
    CampaignListResponse,
    IndustryMetrics,
    IndustriesResponse,
    SystemHealthResponse,
    GrantPlanRequest,
    RevokePlanRequest,
    GrantPlanResponse,
)
from app.services.superadmin_service import (
    SuperAdminAuthService,
    PlatformInsightsService,
)
from app.services.superadmin_phase2_service import (
    CampaignService,
    IndustryInsightsService,
    SystemHealthService,
)
from app.services.audit_service import log_action


router = APIRouter(prefix="/superadmin", tags=["SuperAdmin"])


# ---------------- Auth ----------------

@router.post("/auth/google", response_model=SuperAdminAuthResponse)
def superadmin_google_login(
    data: SuperAdminGoogleAuthRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Login via Google. Only emails on the superadmin allow-list succeed."""
    result = SuperAdminAuthService.login_with_google(db, data.credential)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authorized. This Google account is not a platform administrator.",
        )
    admin, token = result
    log_action(
        db,
        admin,
        "login",
        ip_address=request.client.host if request.client else None,
    )
    return SuperAdminAuthResponse(
        access_token=token,
        admin=SuperAdminResponse.model_validate(admin),
    )


@router.get("/auth/me", response_model=SuperAdminResponse)
def superadmin_me(admin: SuperAdmin = Depends(require_superadmin)):
    return SuperAdminResponse.model_validate(admin)


# ---------------- Insights ----------------

@router.get("/insights", response_model=PlatformInsightsResponse)
def get_platform_insights(
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    return PlatformInsightsService.get_insights(db)


# ---------------- Organizations ----------------

@router.get("/organizations", response_model=OrgListResponse)
def list_organizations(
    q: Optional[str] = None,
    industry: Optional[str] = None,
    plan_status: Optional[str] = None,
    plan_code: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    query = db.query(Organization)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            or_(
                func.lower(Organization.name).like(like),
                func.lower(Organization.website).like(like),
            )
        )
    if industry:
        query = query.filter(Organization.industry == industry)
    if plan_status:
        query = query.filter(Organization.plan_status == plan_status)
    if plan_code:
        query = query.filter(Organization.plan_code == plan_code)

    total = query.count()
    orgs = (
        query.order_by(Organization.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    org_ids = [o.id for o in orgs]
    user_counts = dict(
        db.query(User.org_id, func.count(User.id))
        .filter(User.org_id.in_(org_ids))
        .group_by(User.org_id)
        .all()
    ) if org_ids else {}
    room_counts = dict(
        db.query(Room.org_id, func.count(Room.id))
        .filter(Room.org_id.in_(org_ids))
        .group_by(Room.org_id)
        .all()
    ) if org_ids else {}
    integration_counts = dict(
        db.query(Integration.org_id, func.count(Integration.id))
        .filter(Integration.org_id.in_(org_ids))
        .group_by(Integration.org_id)
        .all()
    ) if org_ids else {}

    items = [
        OrgListItem(
            id=o.id,
            name=o.name,
            industry=o.industry,
            website=o.website,
            plan_code=o.plan_code,
            plan_status=o.plan_status,
            plan_current_end=o.plan_current_end,
            created_at=o.created_at,
            user_count=user_counts.get(o.id, 0),
            room_count=room_counts.get(o.id, 0),
            integration_count=integration_counts.get(o.id, 0),
        )
        for o in orgs
    ]

    return OrgListResponse(items=items, total=total)


@router.get("/organizations/{org_id}", response_model=OrgDetailResponse)
def get_organization_detail(
    org_id: UUID,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    users = (
        db.query(User)
        .filter(User.org_id == org_id)
        .order_by(User.created_at.asc())
        .all()
    )
    subs = (
        db.query(Subscription)
        .filter(Subscription.org_id == org_id)
        .order_by(Subscription.created_at.desc())
        .all()
    )
    integrations = (
        db.query(Integration)
        .filter(Integration.org_id == org_id)
        .order_by(Integration.created_at.desc())
        .all()
    )

    kpi_count = db.query(func.count(KPIDefinition.id)).filter(
        KPIDefinition.org_id == org_id
    ).scalar() or 0
    room_count = db.query(func.count(Room.id)).filter(
        Room.org_id == org_id
    ).scalar() or 0
    entry_count = db.query(func.count(DataEntry.id)).filter(
        DataEntry.org_id == org_id
    ).scalar() or 0

    return OrgDetailResponse(
        id=org.id,
        name=org.name,
        industry=org.industry,
        website=org.website,
        plan_code=org.plan_code,
        plan_status=org.plan_status,
        plan_current_end=org.plan_current_end,
        created_at=org.created_at,
        users=[OrgDetailUser.model_validate(u) for u in users],
        subscriptions=[OrgDetailSubscription.model_validate(s) for s in subs],
        integrations=[OrgDetailIntegration.model_validate(i) for i in integrations],
        kpi_count=kpi_count,
        room_count=room_count,
        entry_count=entry_count,
    )


# ---------------- Users (global) ----------------

@router.get("/users", response_model=GlobalUserListResponse)
def list_all_users(
    q: Optional[str] = None,
    role: Optional[str] = None,
    org_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    query = db.query(User, Organization.name).join(
        Organization, User.org_id == Organization.id
    )
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            or_(
                func.lower(User.email).like(like),
                func.lower(User.name).like(like),
            )
        )
    if role:
        query = query.filter(User.role == role)
    if org_id:
        query = query.filter(User.org_id == org_id)

    total = query.count()
    rows = (
        query.order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    items = [
        GlobalUserItem(
            id=u.id,
            email=u.email,
            name=u.name,
            role=u.role,
            role_label=u.role_label,
            auth_provider=u.auth_provider,
            created_at=u.created_at,
            org_id=u.org_id,
            org_name=org_name,
        )
        for u, org_name in rows
    ]
    return GlobalUserListResponse(items=items, total=total)


# ---------------- Subscriptions (global) ----------------

@router.get("/subscriptions", response_model=GlobalSubscriptionListResponse)
def list_all_subscriptions(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    plan_code: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    query = db.query(Subscription, Organization.name).join(
        Organization, Subscription.org_id == Organization.id
    )
    if status_filter:
        query = query.filter(Subscription.status == status_filter)
    if plan_code:
        query = query.filter(Subscription.plan_code == plan_code)

    total = query.count()
    rows = (
        query.order_by(Subscription.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    items = [
        GlobalSubscriptionItem(
            id=s.id,
            org_id=s.org_id,
            org_name=org_name,
            plan_code=s.plan_code,
            status=s.status,
            razorpay_subscription_id=s.razorpay_subscription_id,
            current_start=s.current_start,
            current_end=s.current_end,
            paid_count=s.paid_count,
            total_count=s.total_count,
            created_at=s.created_at,
        )
        for s, org_name in rows
    ]
    return GlobalSubscriptionListResponse(items=items, total=total)


# ---------------- Manual plan grants (comp accounts, beta testers) ----------------

MANUAL_SUB_PREFIX = "manual_"


@router.post(
    "/organizations/{org_id}/grant-plan",
    response_model=GrantPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def grant_plan(
    org_id: UUID,
    data: GrantPlanRequest,
    request: Request,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Manually grant a subscription plan to an organization without payment.

    Creates a synthetic Subscription record (flagged via ``razorpay_subscription_id``
    prefix ``manual_``) and mirrors the active plan onto the Organization so
    normal entitlement checks apply.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    now = datetime.utcnow()
    current_end = now + timedelta(days=data.duration_days)

    sub = Subscription(
        org_id=org_id,
        plan_code=data.plan_code,
        razorpay_plan_id=f"{MANUAL_SUB_PREFIX}{data.plan_code}",
        razorpay_subscription_id=f"{MANUAL_SUB_PREFIX}{uuid4().hex}",
        status="active",
        paid_count=0,
        total_count=None,
        current_start=now,
        current_end=current_end,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    # Mirror onto the organization so entitlement checks pick it up.
    org.plan_code = data.plan_code
    org.plan_status = "active"
    org.plan_current_end = current_end
    db.commit()
    db.refresh(sub)

    log_action(
        db,
        admin,
        "plan_granted",
        target_type="organization",
        target_id=org_id,
        details={
            "org_name": org.name,
            "plan_code": data.plan_code,
            "duration_days": data.duration_days,
            "current_end": current_end.isoformat(),
            "reason": data.reason,
            "subscription_id": str(sub.id),
        },
        ip_address=request.client.host if request.client else None,
    )
    return GrantPlanResponse.model_validate(sub)


@router.post(
    "/organizations/{org_id}/revoke-plan",
    response_model=GrantPlanResponse,
)
def revoke_plan(
    org_id: UUID,
    data: RevokePlanRequest,
    request: Request,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Revoke an active manually-granted plan for an organization.

    Only cancels manual subscriptions — Razorpay-backed subscriptions must be
    cancelled through the normal billing flow to keep local state in sync with
    Razorpay.
    """
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    sub = (
        db.query(Subscription)
        .filter(
            Subscription.org_id == org_id,
            Subscription.status == "active",
            Subscription.razorpay_subscription_id.like(f"{MANUAL_SUB_PREFIX}%"),
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if sub is None:
        raise HTTPException(
            status_code=404,
            detail="No active manually-granted plan found for this organization",
        )

    now = datetime.utcnow()
    sub.status = "cancelled"
    sub.ended_at = now
    org.plan_code = None
    org.plan_status = "cancelled"
    org.plan_current_end = now
    db.commit()
    db.refresh(sub)

    log_action(
        db,
        admin,
        "plan_revoked",
        target_type="organization",
        target_id=org_id,
        details={
            "org_name": org.name,
            "plan_code": sub.plan_code,
            "reason": data.reason,
            "subscription_id": str(sub.id),
        },
        ip_address=request.client.host if request.client else None,
    )
    return GrantPlanResponse.model_validate(sub)


@router.get("/plans", response_model=list[dict])
def list_available_plans(
    admin: SuperAdmin = Depends(require_superadmin),
):
    """Return the plan codes configured via RAZORPAY_PLAN_IDS for grant dropdowns."""
    from app.services.razorpay_service import RazorpayService
    try:
        return RazorpayService.list_plans()
    except Exception:
        return []


# ---------------- Admin management (manage superadmin allow-list) ----------------

@router.get("/admins", response_model=list[SuperAdminResponse])
def list_superadmins(
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    admins = db.query(SuperAdmin).order_by(SuperAdmin.created_at.asc()).all()
    return [SuperAdminResponse.model_validate(a) for a in admins]


@router.post(
    "/admins",
    response_model=SuperAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_superadmin_entry(
    data: CreateSuperAdminRequest,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    email = data.email.lower().strip()
    existing = (
        db.query(SuperAdmin).filter(func.lower(SuperAdmin.email) == email).first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Super-administrator with this email already exists",
        )

    new_admin = SuperAdmin(
        email=email,
        name=data.name,
        is_active=True,
        created_by_email=admin.email,
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    log_action(
        db,
        admin,
        "admin_created",
        target_type="superadmin",
        target_id=new_admin.id,
        details={"email": new_admin.email},
    )
    return SuperAdminResponse.model_validate(new_admin)


@router.patch("/admins/{admin_id}", response_model=SuperAdminResponse)
def update_superadmin_entry(
    admin_id: UUID,
    data: UpdateSuperAdminRequest,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    target = db.query(SuperAdmin).filter(SuperAdmin.id == admin_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Super-administrator not found")

    if data.is_active is not None:
        # Prevent locking yourself out
        if target.id == admin.id and data.is_active is False:
            raise HTTPException(
                status_code=400,
                detail="You cannot deactivate your own super-admin account",
            )
        target.is_active = data.is_active

    if data.name is not None:
        target.name = data.name

    db.commit()
    db.refresh(target)
    log_action(
        db,
        admin,
        "admin_updated",
        target_type="superadmin",
        target_id=target.id,
        details=data.model_dump(exclude_none=True),
    )
    return SuperAdminResponse.model_validate(target)


@router.delete("/admins/{admin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_superadmin_entry(
    admin_id: UUID,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    target = db.query(SuperAdmin).filter(SuperAdmin.id == admin_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Super-administrator not found")

    if target.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot delete your own super-admin account",
        )

    # Prevent removing the last active admin
    remaining_active = (
        db.query(func.count(SuperAdmin.id))
        .filter(SuperAdmin.id != admin_id, SuperAdmin.is_active == True)  # noqa: E712
        .scalar()
        or 0
    )
    if remaining_active == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove the last active super-administrator",
        )

    removed_email = target.email
    removed_id = target.id
    db.delete(target)
    db.commit()
    log_action(
        db,
        admin,
        "admin_deleted",
        target_type="superadmin",
        target_id=removed_id,
        details={"email": removed_email},
    )
    return None


# ---------------- Impersonation ----------------

@router.post("/impersonate/{user_id}", response_model=ImpersonationResponse)
def impersonate_user(
    user_id: UUID,
    data: ImpersonationRequest,
    request: Request,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    """Issue an impersonation token letting the super-admin act as the target user."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    org = db.query(Organization).filter(Organization.id == user.org_id).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    access_token, expires_at = create_impersonation_token(
        str(user.id), str(user.org_id), str(admin.id), admin.email
    )
    refresh_token, refresh_expires = create_refresh_token(
        {"sub": str(user.id), "org_id": str(user.org_id)}
    )
    store_refresh_token(db, str(user.id), refresh_token, refresh_expires)

    log_action(
        db,
        admin,
        "impersonation_started",
        target_type="user",
        target_id=user.id,
        details={
            "user_email": user.email,
            "org_id": str(org.id),
            "org_name": org.name,
            "reason": data.reason,
        },
        ip_address=request.client.host if request.client else None,
    )

    return ImpersonationResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "role_label": user.role_label,
            "auth_provider": user.auth_provider,
            "created_at": user.created_at.isoformat(),
        },
        organization={
            "id": str(org.id),
            "name": org.name,
            "industry": org.industry,
            "created_at": org.created_at.isoformat(),
            "plan_code": org.plan_code,
            "plan_status": org.plan_status,
            "plan_current_end": org.plan_current_end.isoformat() if org.plan_current_end else None,
        },
        impersonation={
            "superadmin_email": admin.email,
            "expires_at": expires_at.isoformat(),
        },
    )


# ---------------- Notification campaigns ----------------

@router.post(
    "/campaigns/preview-target",
    response_model=CampaignTargetPreviewResponse,
)
def preview_campaign_target(
    data: CampaignTargetPreviewRequest,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    org_count, user_count = CampaignService.preview(db, data.filter.model_dump())
    return CampaignTargetPreviewResponse(
        org_count=org_count, user_count=user_count
    )


@router.post(
    "/campaigns",
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_campaign(
    data: CreateCampaignRequest,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    campaign = NotificationCampaign(
        created_by_superadmin_id=admin.id,
        created_by_email=admin.email,
        title=data.title,
        body=data.body,
        cta_label=data.cta_label,
        cta_url=data.cta_url,
        channel=data.channel,
        severity=data.severity,
        target_filter=data.target.model_dump(),
        expires_at=data.expires_at,
        status="draft",
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    log_action(
        db,
        admin,
        "campaign_created",
        target_type="campaign",
        target_id=campaign.id,
        details={"title": campaign.title, "channel": campaign.channel},
    )
    return CampaignResponse.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/send", response_model=CampaignResponse)
def send_campaign(
    campaign_id: UUID,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    campaign = (
        db.query(NotificationCampaign)
        .filter(NotificationCampaign.id == campaign_id)
        .first()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == "sent":
        raise HTTPException(status_code=400, detail="Campaign already sent")

    CampaignService.send(db, campaign)
    log_action(
        db,
        admin,
        "campaign_sent",
        target_type="campaign",
        target_id=campaign.id,
        details={
            "title": campaign.title,
            "channel": campaign.channel,
            "org_count": campaign.recipient_org_count,
            "user_count": campaign.recipient_user_count,
        },
    )
    return CampaignResponse.model_validate(campaign)


@router.get("/campaigns", response_model=CampaignListResponse)
def list_campaigns(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    query = db.query(NotificationCampaign)
    if status_filter:
        query = query.filter(NotificationCampaign.status == status_filter)
    total = query.count()
    rows = (
        query.order_by(NotificationCampaign.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return CampaignListResponse(
        items=[CampaignResponse.model_validate(c) for c in rows],
        total=total,
    )


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
def get_campaign(
    campaign_id: UUID,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    campaign = (
        db.query(NotificationCampaign)
        .filter(NotificationCampaign.id == campaign_id)
        .first()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignResponse.model_validate(campaign)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: UUID,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    campaign = (
        db.query(NotificationCampaign)
        .filter(NotificationCampaign.id == campaign_id)
        .first()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status == "sent":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a sent campaign (audit trail retention)",
        )
    db.delete(campaign)
    db.commit()
    log_action(
        db,
        admin,
        "campaign_deleted",
        target_type="campaign",
        target_id=campaign_id,
    )
    return None


# ---------------- Audit log ----------------

@router.get("/audit-log", response_model=AuditLogListResponse)
def list_audit_log(
    q: Optional[str] = None,
    action: Optional[str] = None,
    superadmin_email: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    query = db.query(SuperAdminAuditLog)
    if action:
        query = query.filter(SuperAdminAuditLog.action == action)
    if superadmin_email:
        query = query.filter(
            func.lower(SuperAdminAuditLog.superadmin_email) == superadmin_email.lower()
        )
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            or_(
                func.lower(SuperAdminAuditLog.action).like(like),
                func.lower(SuperAdminAuditLog.superadmin_email).like(like),
                func.lower(SuperAdminAuditLog.target_id).like(like),
            )
        )
    total = query.count()
    rows = (
        query.order_by(SuperAdminAuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return AuditLogListResponse(
        items=[AuditLogItem.model_validate(r) for r in rows],
        total=total,
    )


# ---------------- Industries deep-dive ----------------

@router.get("/industries", response_model=IndustriesResponse)
def industries_breakdown(
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    rows = IndustryInsightsService.get_breakdown(db)
    return IndustriesResponse(items=[IndustryMetrics(**r) for r in rows])


# ---------------- System health ----------------

@router.get("/health", response_model=SystemHealthResponse)
def system_health(
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    return SystemHealthService.get_health(db)


# ---------------- Sales leads (inbound contact forms) ----------------

@router.get("/leads", response_model=SalesLeadListResponse)
def list_sales_leads(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    q: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    query = db.query(SalesLead)
    if status_filter:
        query = query.filter(SalesLead.status == status_filter)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            or_(
                func.lower(SalesLead.email).like(like),
                func.lower(SalesLead.name).like(like),
                func.lower(SalesLead.company).like(like),
            )
        )
    total = query.count()
    rows = (
        query.order_by(SalesLead.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return SalesLeadListResponse(
        items=[SalesLeadResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.patch("/leads/{lead_id}", response_model=SalesLeadResponse)
def update_sales_lead(
    lead_id: UUID,
    data: SalesLeadUpdate,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    lead = db.query(SalesLead).filter(SalesLead.id == lead_id).first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    if data.status is not None:
        lead.status = data.status
    if data.notes is not None:
        lead.notes = data.notes
    db.commit()
    db.refresh(lead)

    log_action(
        db,
        admin,
        "lead_updated",
        target_type="sales_lead",
        target_id=lead_id,
        details={
            "email": lead.email,
            "status": lead.status,
        },
    )
    return SalesLeadResponse.model_validate(lead)


@router.delete("/leads/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sales_lead(
    lead_id: UUID,
    admin: SuperAdmin = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    lead = db.query(SalesLead).filter(SalesLead.id == lead_id).first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    email = lead.email
    db.delete(lead)
    db.commit()
    log_action(
        db,
        admin,
        "lead_deleted",
        target_type="sales_lead",
        target_id=lead_id,
        details={"email": email},
    )
    return None
