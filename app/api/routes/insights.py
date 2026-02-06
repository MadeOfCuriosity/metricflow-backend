from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user_org
from app.models import User, Organization, KPIDefinition
from app.models import DataEntry
from app.schemas.insights import (
    InsightResponse,
    InsightListResponse,
    RefreshInsightsResponse,
    KPIStatisticsResponse,
    OverallStatisticsResponse,
)
from app.services.statistics_service import StatisticsService
from app.services.insight_generator import InsightGenerator


router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("", response_model=InsightListResponse)
def get_insights(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get cached insights for the organization.
    Automatically regenerates if older than 24 hours.
    """
    _, org = user_org

    insights, needs_refresh = InsightGenerator.get_cached_insights(db, org.id)

    # Auto-refresh if needed
    if needs_refresh:
        insights = InsightGenerator.generate_insights(db, org.id)

    # Build response with KPI names
    insight_responses = []
    for insight in insights:
        kpi_name = None
        if insight.kpi_id:
            kpi = db.query(KPIDefinition).filter(
                KPIDefinition.id == insight.kpi_id
            ).first()
            kpi_name = kpi.name if kpi else None

        insight_responses.append(InsightResponse(
            id=insight.id,
            kpi_id=insight.kpi_id,
            kpi_name=kpi_name,
            insight_text=insight.insight_text,
            priority=insight.priority,
            generated_at=insight.generated_at,
        ))

    generated_at = insights[0].generated_at if insights else None

    return InsightListResponse(
        insights=insight_responses,
        total=len(insight_responses),
        generated_at=generated_at,
        needs_refresh=False,  # We just refreshed if needed
    )


@router.post("/refresh", response_model=RefreshInsightsResponse)
def refresh_insights(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Force regenerate insights for the organization.
    """
    _, org = user_org

    insights = InsightGenerator.generate_insights(db, org.id)

    # Build response with KPI names
    insight_responses = []
    for insight in insights:
        kpi_name = None
        if insight.kpi_id:
            kpi = db.query(KPIDefinition).filter(
                KPIDefinition.id == insight.kpi_id
            ).first()
            kpi_name = kpi.name if kpi else None

        insight_responses.append(InsightResponse(
            id=insight.id,
            kpi_id=insight.kpi_id,
            kpi_name=kpi_name,
            insight_text=insight.insight_text,
            priority=insight.priority,
            generated_at=insight.generated_at,
        ))

    return RefreshInsightsResponse(
        message=f"Generated {len(insights)} insights",
        insights_generated=len(insights),
        insights=insight_responses,
    )


@router.get("/statistics", response_model=OverallStatisticsResponse)
def get_overall_statistics(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get overall statistics for the organization.
    """
    _, org = user_org

    # Count KPIs
    kpis_count = db.query(KPIDefinition).filter(
        KPIDefinition.org_id == org.id
    ).count()

    # Count total entries and unique days
    from sqlalchemy import func, distinct

    entries_query = db.query(DataEntry).join(KPIDefinition).filter(
        KPIDefinition.org_id == org.id
    )

    total_entries = entries_query.count()

    days_result = db.query(func.count(distinct(DataEntry.date))).join(
        KPIDefinition
    ).filter(KPIDefinition.org_id == org.id).scalar()

    days_of_data = days_result or 0

    return OverallStatisticsResponse(
        total_entries=total_entries,
        kpis_tracked=kpis_count,
        days_of_data=days_of_data,
    )


@router.get("/statistics/{kpi_id}", response_model=KPIStatisticsResponse)
def get_kpi_statistics(
    kpi_id: UUID,
    period_days: int = Query(30, ge=7, le=365, description="Analysis period in days"),
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get detailed statistics for a specific KPI.
    """
    _, org = user_org

    stats = StatisticsService.calculate_stats(db, org.id, kpi_id, period_days)

    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KPI not found",
        )

    return KPIStatisticsResponse(
        kpi_id=stats.kpi_id,
        kpi_name=stats.kpi_name,
        period_days=stats.period_days,
        data_points=stats.data_points,
        mean=stats.mean,
        median=stats.median,
        std_dev=stats.std_dev,
        min_value=stats.min_value,
        max_value=stats.max_value,
        percentile_25=stats.percentile_25,
        percentile_75=stats.percentile_75,
        percentile_90=stats.percentile_90,
        current_value=stats.current_value,
        all_time_high=stats.all_time_high,
        all_time_low=stats.all_time_low,
    )
