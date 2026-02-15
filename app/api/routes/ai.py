from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import update as sa_update

from app.api.deps import get_db, get_current_user_org
from app.core.config import settings
from app.models import User, Organization, AIUsage
from app.schemas.ai import (
    KPIBuilderRequest,
    KPIBuilderResponse,
    KPISuggestionResponse,
    RateLimitStatusResponse,
    AdminAgentRequest,
    AdminAgentResponse,
)
from app.services.ai_service import AIService, ConversationMessage
from app.services.admin_ai_service import AdminAIService, ConversationMessage as AdminConversationMessage
from app.api.deps import require_admin_org


router = APIRouter(prefix="/ai", tags=["AI"])


def get_or_create_usage(db: Session, org_id: UUID, today: date) -> AIUsage:
    """Get or create AI usage record for today."""
    usage = db.query(AIUsage).filter(
        AIUsage.org_id == org_id,
        AIUsage.usage_date == today
    ).first()

    if not usage:
        usage = AIUsage(
            org_id=org_id,
            usage_date=today,
            call_count=0
        )
        db.add(usage)
        db.commit()
        db.refresh(usage)

    return usage


def check_rate_limit(db: Session, org_id: UUID) -> tuple[bool, int]:
    """Check if org is within rate limit. Returns (allowed, remaining)."""
    today = date.today()
    usage = get_or_create_usage(db, org_id, today)
    limit = settings.AI_RATE_LIMIT_PER_DAY
    remaining = max(0, limit - usage.call_count)
    return usage.call_count < limit, remaining


def increment_usage_atomic(db: Session, org_id: UUID) -> tuple[bool, int]:
    """
    Atomically check rate limit and increment usage in a single query.
    Returns (was_allowed, remaining_after).
    """
    today = date.today()
    limit = settings.AI_RATE_LIMIT_PER_DAY
    usage = get_or_create_usage(db, org_id, today)

    # Atomic conditional increment: only increment if under limit
    result = db.execute(
        sa_update(AIUsage)
        .where(
            AIUsage.org_id == org_id,
            AIUsage.usage_date == today,
            AIUsage.call_count < limit,
        )
        .values(call_count=AIUsage.call_count + 1)
    )
    db.commit()

    if result.rowcount == 0:
        # Limit was already reached
        return False, 0

    db.refresh(usage)
    remaining = max(0, limit - usage.call_count)
    return True, remaining


@router.post("/kpi-builder", response_model=KPIBuilderResponse)
async def kpi_builder(
    data: KPIBuilderRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    AI-powered KPI builder conversation endpoint.

    Maintains conversation context and generates KPI suggestions.
    Rate limited to prevent abuse.
    """
    _, org = user_org

    # Atomically reserve a rate limit slot before making the API call
    allowed, remaining = increment_usage_atomic(db, org.id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. You have used all {settings.AI_RATE_LIMIT_PER_DAY} AI calls for today. Resets at midnight UTC.",
        )

    # Convert conversation history
    history = [
        ConversationMessage(role=msg.role, content=msg.content)
        for msg in data.conversation_history
    ]

    # Check if Gemini API is configured
    if not settings.GEMINI_API_KEY:
        # Use mock response for development/testing
        response = AIService.generate_response_mock(history, data.user_message)
    else:
        # Use Gemini API
        response = await AIService.generate_response(history, data.user_message)

    # Build response
    suggested_kpi = None
    if response.suggestion:
        suggested_kpi = KPISuggestionResponse(
            name=response.suggestion.name,
            formula=response.suggestion.formula,
            input_fields=response.suggestion.input_fields,
            description=response.suggestion.description,
            category=response.suggestion.category,
            time_period=response.suggestion.time_period,
        )

    return KPIBuilderResponse(
        ai_response=response.text,
        suggested_kpi=suggested_kpi,
        error=response.error,
        rate_limit_remaining=remaining,
    )


@router.get("/rate-limit", response_model=RateLimitStatusResponse)
def get_rate_limit_status(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get current AI rate limit status for the organization.
    """
    _, org = user_org

    allowed, remaining = check_rate_limit(db, org.id)

    # Calculate reset time (midnight UTC)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    reset_time = datetime.combine(tomorrow, datetime.min.time())

    return RateLimitStatusResponse(
        allowed=allowed,
        remaining_calls=remaining,
        limit_per_day=settings.AI_RATE_LIMIT_PER_DAY,
        resets_at=reset_time.isoformat() + "Z",
    )


@router.post("/admin-agent", response_model=AdminAgentResponse)
async def admin_agent(
    data: AdminAgentRequest,
    user_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    AI-powered admin assistant with full org data context.
    Admin-only endpoint. Shares rate limit with KPI builder.
    """
    _, org = user_org

    # Atomically reserve a rate limit slot before making the API call
    allowed, remaining = increment_usage_atomic(db, org.id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. You have used all {settings.AI_RATE_LIMIT_PER_DAY} AI calls for today. Resets at midnight UTC.",
        )

    # Convert conversation history
    history = [
        AdminConversationMessage(role=msg.role, content=msg.content)
        for msg in data.conversation_history
    ]

    # Check if Gemini API is configured
    if not settings.GEMINI_API_KEY:
        response = AdminAIService.generate_response_mock(
            db, org.id, history, data.user_message
        )
    else:
        response = await AdminAIService.generate_response(
            db, org.id, history, data.user_message
        )

    return AdminAgentResponse(
        ai_response=response.text,
        error=response.error,
        rate_limit_remaining=remaining,
    )
