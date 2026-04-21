from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models import User
from app.schemas.superadmin_phase2 import ActiveNotification
from app.services.superadmin_phase2_service import InboxService


router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/active", response_model=list[ActiveNotification])
def get_active_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return undismissed in-app campaigns targeted at the current user's org."""
    campaigns = InboxService.get_active_for_user(db, current_user)
    return [ActiveNotification.model_validate(c) for c in campaigns]


@router.post(
    "/{campaign_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
def dismiss_notification(
    campaign_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    InboxService.dismiss(db, current_user, campaign_id)
    return None
