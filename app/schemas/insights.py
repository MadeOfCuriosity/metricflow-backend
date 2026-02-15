from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class InsightResponse(BaseModel):
    id: UUID
    kpi_id: Optional[UUID]
    kpi_name: Optional[str] = None
    insight_text: str
    priority: str  # "high", "medium", "low"
    generated_at: datetime

    model_config = {"from_attributes": True}


class InsightListResponse(BaseModel):
    insights: list[InsightResponse]
    total: int
    generated_at: Optional[datetime]
    needs_refresh: bool


class RefreshInsightsResponse(BaseModel):
    message: str
    insights_generated: int
    insights: list[InsightResponse]


class OverallStatisticsResponse(BaseModel):
    total_entries: int
    kpis_tracked: int
    days_of_data: int


class KPIStatisticsResponse(BaseModel):
    kpi_id: UUID
    kpi_name: str
    period_days: int
    data_points: int
    mean: Optional[float]
    median: Optional[float]
    std_dev: Optional[float]
    min_value: Optional[float]
    max_value: Optional[float]
    percentile_25: Optional[float]
    percentile_75: Optional[float]
    percentile_90: Optional[float]
    current_value: Optional[float]
    all_time_high: Optional[float]
    all_time_low: Optional[float]
