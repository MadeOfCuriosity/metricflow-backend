from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- Data source picker (existing KPIs / Data Fields to connect) ---

class DataSourceOption(BaseModel):
    id: UUID
    name: str


class DataSourceOptionsResponse(BaseModel):
    kpis: list[DataSourceOption]
    data_fields: list[DataSourceOption]


# --- Recipients (managed inside the app) ---

class RecipientUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=6, max_length=32)
    notes: Optional[str] = Field(None, max_length=1000)


class RecipientResponse(BaseModel):
    id: UUID
    name: str
    phone: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecipientListResponse(BaseModel):
    recipients: list[RecipientResponse]
    total: int


class RecipientsCsvImportResponse(BaseModel):
    imported: int
    errors: list[str] = Field(default_factory=list)


# --- Suppression list (opt-out) ---

class SuppressionCreateRequest(BaseModel):
    phone: str = Field(..., min_length=6, max_length=32)
    reason: Optional[str] = Field(None, max_length=255)


class SuppressionResponse(BaseModel):
    id: UUID
    phone: str
    reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SuppressionListResponse(BaseModel):
    suppressions: list[SuppressionResponse]


# --- Per-recipient send log (read-only, phone masked) ---

class SendLogResponse(BaseModel):
    id: UUID
    run_id: Optional[UUID] = None
    recipient_name: Optional[str] = None
    phone_masked: str
    data_value: Optional[str] = None
    template_used: Optional[str] = None
    whatsapp_message_id: Optional[str] = None
    delivery_status: str
    error: Optional[str] = None
    created_at: datetime


class SendLogListResponse(BaseModel):
    logs: list[SendLogResponse]
    total: int
