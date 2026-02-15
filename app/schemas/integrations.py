from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- Request schemas ---

class CreateIntegrationRequest(BaseModel):
    provider: str = Field(..., pattern="^(google_sheets|zoho_crm|leadsquared)$")
    display_name: str = Field(..., min_length=1, max_length=255)
    sync_schedule: str = Field("manual", pattern="^(manual|1h|6h|12h|24h)$")
    config: dict = Field(default_factory=dict)
    # LeadSquared only
    api_key: Optional[str] = None
    api_secret: Optional[str] = None


class UpdateIntegrationRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    sync_schedule: Optional[str] = Field(None, pattern="^(manual|1h|6h|12h|24h)$")
    config: Optional[dict] = None


class FieldMappingInput(BaseModel):
    external_field_name: str = Field(..., min_length=1)
    external_field_label: Optional[str] = None
    data_field_id: UUID
    aggregation: str = Field("direct", pattern="^(direct|count|sum|avg|min|max)$")
    filter_criteria: Optional[dict] = None


class SetFieldMappingsRequest(BaseModel):
    mappings: list[FieldMappingInput] = Field(..., min_length=1)


# --- Response schemas ---

class IntegrationResponse(BaseModel):
    id: UUID
    org_id: UUID
    provider: str
    display_name: str
    status: str
    error_message: Optional[str] = None
    config: dict = Field(default_factory=dict)
    sync_schedule: str
    last_synced_at: Optional[datetime] = None
    next_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    mapping_count: int = 0

    model_config = {"from_attributes": True}


class IntegrationListResponse(BaseModel):
    integrations: list[IntegrationResponse]
    total: int


class FieldMappingResponse(BaseModel):
    id: UUID
    integration_id: UUID
    data_field_id: UUID
    data_field_name: str = ""
    external_field_name: str
    external_field_label: Optional[str] = None
    aggregation: str
    is_active: bool

    model_config = {"from_attributes": True}


class FieldMappingListResponse(BaseModel):
    mappings: list[FieldMappingResponse]
    total: int


class ExternalFieldResponse(BaseModel):
    name: str
    label: str
    field_type: str


class ExternalFieldListResponse(BaseModel):
    fields: list[ExternalFieldResponse]
    total: int


class SyncLogResponse(BaseModel):
    id: UUID
    integration_id: UUID
    status: str
    trigger_type: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    rows_fetched: int
    rows_written: int
    rows_skipped: int
    errors_count: int
    error_details: Optional[list] = None
    summary: Optional[str] = None

    model_config = {"from_attributes": True}


class SyncLogListResponse(BaseModel):
    logs: list[SyncLogResponse]
    total: int


class IntegrationDetailResponse(IntegrationResponse):
    field_mappings: list[FieldMappingResponse] = []
    recent_logs: list[SyncLogResponse] = []


class OAuthAuthorizeResponse(BaseModel):
    authorize_url: str
    state: str
