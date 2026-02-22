from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

EntryInterval = Literal["daily", "weekly", "monthly", "custom"]


# --- DataField CRUD Schemas ---

class DataFieldCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    room_id: Optional[UUID] = None
    description: Optional[str] = None
    unit: Optional[str] = Field(None, max_length=50)
    entry_interval: EntryInterval = "daily"


class DataFieldUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    unit: Optional[str] = Field(None, max_length=50)
    room_id: Optional[UUID] = None
    entry_interval: Optional[EntryInterval] = None


class DataFieldBrief(BaseModel):
    """Brief data field info for embedding in KPI responses."""
    id: UUID
    name: str
    variable_name: str
    room_id: Optional[UUID]
    room_name: Optional[str] = None

    model_config = {"from_attributes": True}


class DataFieldResponse(BaseModel):
    id: UUID
    org_id: UUID
    room_id: Optional[UUID]
    room_name: Optional[str] = None
    room_path: Optional[str] = None
    name: str
    variable_name: str
    description: Optional[str]
    unit: Optional[str]
    entry_interval: str = "daily"
    created_by: Optional[UUID]
    created_at: datetime
    kpi_count: int = 0
    latest_value: Optional[float] = None
    latest_date: Optional[date] = None

    model_config = {"from_attributes": True}


class DataFieldListResponse(BaseModel):
    data_fields: list[DataFieldResponse]
    total: int


# --- Per-Field Entry Schemas ---

class FieldEntryInput(BaseModel):
    data_field_id: UUID
    value: float


class CreateFieldEntriesRequest(BaseModel):
    date: date
    entries: list[FieldEntryInput] = Field(..., min_length=1)


class FieldEntryResponse(BaseModel):
    id: UUID
    data_field_id: UUID
    data_field_name: Optional[str] = None
    room_name: Optional[str] = None
    date: date
    value: float
    entered_by: Optional[UUID]
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateFieldEntriesResponse(BaseModel):
    message: str
    entries_created: int
    entries: list[FieldEntryResponse]
    kpis_recalculated: int = 0
    errors: list[dict]


# --- Today's Field Form Schemas ---

class FieldFormItem(BaseModel):
    data_field_id: UUID
    data_field_name: str
    variable_name: str
    unit: Optional[str] = None
    entry_interval: str = "daily"
    has_entry_today: bool
    today_value: Optional[float] = None


class RoomFieldGroup(BaseModel):
    room_id: Optional[UUID]
    room_name: str
    fields: list[FieldFormItem]


class TodayFieldFormResponse(BaseModel):
    date: date
    interval: Optional[str] = None
    rooms: list[RoomFieldGroup]
    completed_count: int
    total_count: int


# --- CSV Import Schemas ---

class CSVImportResponse(BaseModel):
    rows_processed: int
    entries_created: int
    kpis_recalculated: int
    errors: list[dict]
    unmatched_columns: list[str]
