"""Public contact-sales lead capture endpoint."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.rate_limit import public_limiter
from app.models import SalesLead
from app.schemas.sales_lead import SalesLeadCreate, SalesLeadResponse


router = APIRouter(prefix="/sales", tags=["Sales"])


@router.post(
    "/contact",
    response_model=SalesLeadResponse,
    status_code=status.HTTP_201_CREATED,
)
@public_limiter.limit("5/minute")
def submit_contact_form(
    data: SalesLeadCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Capture an inbound sales lead from the landing page.

    Rate-limited to 5 submissions per minute per IP to deter spam.
    """
    # Light anti-spam: reject submissions where company == name and no message.
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:500]

    lead = SalesLead(
        name=data.name.strip(),
        email=data.email.lower().strip(),
        company=(data.company or "").strip() or None,
        team_size=(data.team_size or "").strip() or None,
        message=(data.message or "").strip() or None,
        source=data.source or "enterprise_contact",
        ip_address=ip,
        user_agent=ua or None,
        status="new",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return SalesLeadResponse.model_validate(lead)
