from datetime import datetime
from typing import Optional, List, Literal
from uuid import UUID

from pydantic import BaseModel, Field


# --- Impersonation ---

class ImpersonationRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class ImpersonationResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict
    organization: dict
    impersonation: dict  # { superadmin_email, expires_at }


# --- Audit log ---

class AuditLogItem(BaseModel):
    id: UUID
    superadmin_id: Optional[UUID] = None
    superadmin_email: str
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    details: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItem]
    total: int


# --- Notification campaigns ---

NotificationSeverity = Literal["info", "warning", "success", "announcement"]
NotificationChannel = Literal["in_app", "email"]


class CampaignTargetFilter(BaseModel):
    all: bool = False
    industries: Optional[List[str]] = None
    plan_codes: Optional[List[str]] = None
    plan_statuses: Optional[List[str]] = None


class CampaignTargetPreviewRequest(BaseModel):
    filter: CampaignTargetFilter


class CampaignTargetPreviewResponse(BaseModel):
    org_count: int
    user_count: int


class CreateCampaignRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    cta_label: Optional[str] = Field(default=None, max_length=100)
    cta_url: Optional[str] = Field(default=None, max_length=512)
    channel: NotificationChannel = "in_app"
    severity: NotificationSeverity = "info"
    target: CampaignTargetFilter
    expires_at: Optional[datetime] = None


class CampaignResponse(BaseModel):
    id: UUID
    created_by_email: str
    title: str
    body: str
    cta_label: Optional[str] = None
    cta_url: Optional[str] = None
    channel: str
    severity: str
    status: str
    target_filter: Optional[dict] = None
    recipient_org_count: Optional[int] = None
    recipient_user_count: Optional[int] = None
    sent_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignListResponse(BaseModel):
    items: List[CampaignResponse]
    total: int


# --- Active banners for org users ---

class ActiveNotification(BaseModel):
    id: UUID
    title: str
    body: str
    cta_label: Optional[str] = None
    cta_url: Optional[str] = None
    severity: str
    sent_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# --- Industries deep-dive ---

class IndustryMetrics(BaseModel):
    industry: str
    org_count: int
    user_count: int
    active_subscriptions: int
    orgs_with_integrations: int
    orgs_with_kpis: int
    orgs_with_data: int
    mrr: float


class IndustriesResponse(BaseModel):
    items: List[IndustryMetrics]


# --- System health ---

class HealthIntegrationFailure(BaseModel):
    org_id: UUID
    org_name: str
    provider: str
    status: str
    error_message: Optional[str] = None
    last_sync_at: Optional[datetime] = None


class HealthWebhookSummary(BaseModel):
    total_events_7d: int
    failed_events_7d: int
    last_event_at: Optional[datetime] = None


class HealthAIUsage(BaseModel):
    calls_30d: int
    orgs_using_ai_30d: int


class HealthSyncSummary(BaseModel):
    total_syncs_7d: int
    failed_syncs_7d: int
    last_sync_at: Optional[datetime] = None


class SystemHealthResponse(BaseModel):
    integration_failures: List[HealthIntegrationFailure]
    webhooks: HealthWebhookSummary
    syncs: HealthSyncSummary
    ai_usage: HealthAIUsage
