from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SuperAdminGoogleAuthRequest(BaseModel):
    credential: str  # Google ID token from @react-oauth/google


class SuperAdminResponse(BaseModel):
    id: UUID
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: datetime
    created_by_email: Optional[str] = None

    model_config = {"from_attributes": True}


class SuperAdminAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: SuperAdminResponse


class CreateSuperAdminRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = Field(default=None, max_length=255)


class UpdateSuperAdminRequest(BaseModel):
    is_active: Optional[bool] = None
    name: Optional[str] = Field(default=None, max_length=255)


# --- Platform insights ---
class PlatformInsightsResponse(BaseModel):
    total_orgs: int
    total_users: int
    active_subscriptions: int
    mrr: float
    orgs_created_30d: int
    users_created_30d: int
    signups_by_day: List[dict]  # [{date, orgs, users}]
    orgs_by_industry: List[dict]  # [{industry, count}]
    orgs_by_plan: List[dict]  # [{plan_code, count}]
    orgs_by_plan_status: List[dict]  # [{plan_status, count}]
    feature_adoption: dict  # {with_integrations, with_kpis, with_rooms, with_data}


# --- Organizations ---
class OrgListItem(BaseModel):
    id: UUID
    name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    plan_code: Optional[str] = None
    plan_status: Optional[str] = None
    plan_current_end: Optional[datetime] = None
    created_at: datetime
    user_count: int
    room_count: int
    integration_count: int

    model_config = {"from_attributes": True}


class OrgListResponse(BaseModel):
    items: List[OrgListItem]
    total: int


class OrgDetailUser(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    role_label: Optional[str] = None
    auth_provider: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgDetailSubscription(BaseModel):
    id: UUID
    plan_code: str
    status: str
    razorpay_subscription_id: Optional[str] = None
    current_start: Optional[datetime] = None
    current_end: Optional[datetime] = None
    paid_count: int
    total_count: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgDetailIntegration(BaseModel):
    id: UUID
    provider: str
    status: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgDetailResponse(BaseModel):
    id: UUID
    name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    plan_code: Optional[str] = None
    plan_status: Optional[str] = None
    plan_current_end: Optional[datetime] = None
    created_at: datetime
    users: List[OrgDetailUser]
    subscriptions: List[OrgDetailSubscription]
    integrations: List[OrgDetailIntegration]
    kpi_count: int
    room_count: int
    entry_count: int


# --- Users (global) ---
class GlobalUserItem(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    role_label: Optional[str] = None
    auth_provider: Optional[str] = None
    created_at: datetime
    org_id: UUID
    org_name: str

    model_config = {"from_attributes": True}


class GlobalUserListResponse(BaseModel):
    items: List[GlobalUserItem]
    total: int


# --- Subscriptions (global) ---
class GlobalSubscriptionItem(BaseModel):
    id: UUID
    org_id: UUID
    org_name: str
    plan_code: str
    status: str
    razorpay_subscription_id: Optional[str] = None
    current_start: Optional[datetime] = None
    current_end: Optional[datetime] = None
    paid_count: int
    total_count: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class GlobalSubscriptionListResponse(BaseModel):
    items: List[GlobalSubscriptionItem]
    total: int
