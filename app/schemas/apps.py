from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- App metadata (from the registry, not the DB) ---

class AppConfigFieldResponse(BaseModel):
    key: str
    label: str
    field_type: str
    required: bool = False
    secret: bool = False
    options: Optional[list[str]] = None
    default: Any = None
    help_text: Optional[str] = None


class SecretFieldStatus(BaseModel):
    configured: bool
    last4: Optional[str] = None


class AppInstallationResponse(BaseModel):
    id: UUID
    org_id: UUID
    app_key: str
    is_enabled: bool
    entitlement_status: str
    config: dict = Field(default_factory=dict)
    # Never plaintext — configured/last-4 only per secret field. Populated by
    # the route handler after model_validate (the ORM row has no such
    # attribute; see app_secret_config.secret_config_status).
    secret_config_status: dict[str, SecretFieldStatus] = Field(default_factory=dict)
    installed_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AppSummaryResponse(BaseModel):
    """Merges registry metadata for one app with this org's installation (if any)."""
    key: str
    name: str
    description: str
    requires_entitlement: bool
    triggers: list[str]
    default_schedule: Optional[str] = None
    config_schema: list[AppConfigFieldResponse]
    installation: Optional[AppInstallationResponse] = None


class AppListResponse(BaseModel):
    apps: list[AppSummaryResponse]


# --- Requests ---

class ConfigureAppRequest(BaseModel):
    config: dict = Field(default_factory=dict)


class SetSecretConfigRequest(BaseModel):
    """Plaintext secret values, accepted once over HTTPS and immediately
    Fernet-encrypted server-side — never echoed back or logged."""
    secret_config: dict = Field(default_factory=dict)


class RunAppRequest(BaseModel):
    idempotency_key: Optional[str] = None


class SetEntitlementRequest(BaseModel):
    entitlement_status: str = Field(..., pattern="^(not_required|required|granted|revoked)$")


# --- Run records ---

class AppRunRecordResponse(BaseModel):
    id: UUID
    installation_id: UUID
    org_id: UUID
    app_key: str
    status: str
    trigger_type: str
    triggered_by: Optional[UUID] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    summary: Optional[str] = None

    model_config = {"from_attributes": True}


class AppRunRecordListResponse(BaseModel):
    runs: list[AppRunRecordResponse]
    total: int
