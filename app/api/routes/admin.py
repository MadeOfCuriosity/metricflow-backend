from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin_org
from app.models import User, Organization
from app.schemas.admin import AdminStatsResponse, ActivityFeedResponse
from app.services.admin_stats_service import AdminStatsService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStatsResponse)
def get_admin_stats(
    days: int = Query(default=30, ge=1, le=90),
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Get aggregated organization statistics for the admin dashboard."""
    _, org = admin_org

    stats = AdminStatsService.get_org_stats(db, org.id)
    completion_rate = AdminStatsService.get_completion_rates(db, org.id, days)

    return AdminStatsResponse(
        **stats,
        completion_rate=completion_rate,
    )


@router.get("/activity", response_model=ActivityFeedResponse)
def get_admin_activity(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Get recent activity feed across the organization."""
    _, org = admin_org

    activities, total = AdminStatsService.get_activity_feed(
        db, org.id, limit, offset
    )

    return ActivityFeedResponse(activities=activities, total=total)
