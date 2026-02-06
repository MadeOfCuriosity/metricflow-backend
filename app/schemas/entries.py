from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# Request schemas
class EntryValueInput(BaseModel):
    kpi_id: UUID
    values: dict[str, float] = Field(..., description="Input field values, e.g., {'revenue': 50000, 'deals_closed': 10}")


class CreateEntriesRequest(BaseModel):
    date: date
    entries: list[EntryValueInput] = Field(..., min_length=1)


# Response schemas
class DataEntryResponse(BaseModel):
    id: UUID
    kpi_id: UUID
    kpi_name: Optional[str] = None
    date: date
    values: dict
    calculated_value: float
    entered_by: Optional[UUID]
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateEntriesResponse(BaseModel):
    message: str
    entries_created: int
    entries: list[DataEntryResponse]
    errors: list[dict]  # [{kpi_id, error}]


class EntryListResponse(BaseModel):
    entries: list[DataEntryResponse]
    total: int


# Today's form schemas
class KPIInputField(BaseModel):
    name: str
    current_value: Optional[float] = None


class KPIFormItem(BaseModel):
    kpi_id: UUID
    kpi_name: str
    category: str
    formula: str
    input_fields: list[str]
    has_entry_today: bool
    today_entry: Optional[DataEntryResponse] = None


class TodayFormResponse(BaseModel):
    date: date
    kpis: list[KPIFormItem]
    completed_count: int
    total_count: int


# Summary schemas
class StatsSummaryResponse(BaseModel):
    kpi_id: UUID
    kpi_name: str
    period: str
    current_value: Optional[float]
    mean: Optional[float]
    median: Optional[float]
    std_dev: Optional[float]
    min_value: Optional[float]
    max_value: Optional[float]
    trend: Optional[str]  # "up", "down", "stable"
    trend_percentage: Optional[float]
    data_points: int
