from datetime import datetime, date
from typing import Optional, Literal
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.core.formula_parser import validate_formula
from app.schemas.data_fields import DataFieldBrief


class TimePeriodEnum(str, Enum):
    """Time period/frequency for KPI data collection."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    OTHER = "other"


class KPICreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    formula: str = Field(..., min_length=1, max_length=500)
    category: str = Field(..., pattern="^(Sales|Marketing|Operations|Finance|Custom)$")
    time_period: TimePeriodEnum = Field(
        default=TimePeriodEnum.DAILY,
        description="Frequency of data collection for this KPI"
    )
    is_shared: bool = Field(
        default=False,
        description="If true, KPI is visible in all rooms (org-wide)"
    )
    data_field_mappings: Optional[dict[str, UUID]] = Field(
        None,
        description="Explicit mapping of formula variable names to DataField IDs. "
                    "If not provided, variables are auto-resolved or new DataFields created."
    )
    room_id: Optional[UUID] = Field(
        None,
        description="Room to auto-assign this KPI to and scope auto-created data fields"
    )

    @field_validator('formula')
    @classmethod
    def validate_formula_syntax(cls, v: str) -> str:
        is_valid, error, _ = validate_formula(v)
        if not is_valid:
            raise ValueError(f"Invalid formula: {error}")
        return v


class KPIUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    formula: Optional[str] = Field(None, min_length=1, max_length=500)
    category: Optional[str] = Field(None, pattern="^(Sales|Marketing|Operations|Finance|Custom)$")
    time_period: Optional[TimePeriodEnum] = Field(
        None,
        description="Frequency of data collection for this KPI"
    )
    is_shared: Optional[bool] = Field(
        None,
        description="If true, KPI is visible in all rooms (org-wide)"
    )

    @field_validator('formula')
    @classmethod
    def validate_formula_syntax(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            is_valid, error, _ = validate_formula(v)
            if not is_valid:
                raise ValueError(f"Invalid formula: {error}")
        return v


class KPIResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    description: Optional[str]
    formula: str
    input_fields: list[str]
    category: str
    time_period: TimePeriodEnum
    is_preset: bool
    is_shared: bool
    created_by: Optional[UUID]
    created_at: datetime
    data_fields: list[DataFieldBrief] = []
    room_paths: list[str] = []

    model_config = {"from_attributes": True}


class KPIWithDataResponse(BaseModel):
    kpi: KPIResponse
    recent_entries: list  # Will use DataEntryResponse from entries schema


class KPIListResponse(BaseModel):
    kpis: list[KPIResponse]
    total: int


class SeedPresetsResponse(BaseModel):
    message: str
    presets_created: int
    presets: list[KPIResponse]


class PresetInfo(BaseModel):
    """Information about an available preset KPI."""
    name: str
    description: str
    formula: str
    category: str
    time_period: TimePeriodEnum = TimePeriodEnum.DAILY


class AvailablePresetsResponse(BaseModel):
    """Response with list of available presets that can be added."""
    available_presets: list[PresetInfo]
    total: int


class SeedPresetsRequest(BaseModel):
    """Request to seed specific preset KPIs."""
    preset_names: list[str] = Field(..., min_length=1, description="List of preset names to add")
