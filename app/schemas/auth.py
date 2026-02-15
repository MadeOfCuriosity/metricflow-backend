from datetime import datetime
from typing import Optional, Literal, List
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# Role type
RoleType = Literal["admin", "room_admin"]


# Request schemas
class RegisterOrgRequest(BaseModel):
    org_name: str = Field(..., min_length=2, max_length=100)
    admin_name: str = Field(..., min_length=2, max_length=100)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=8, max_length=128)
    industry: Optional[str] = Field(None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class InviteUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=2, max_length=255)
    role: RoleType = Field(default="room_admin", description="User role: 'admin' or 'room_admin'")
    role_label: str = Field(..., min_length=2, max_length=100)
    room_ids: Optional[List[UUID]] = Field(default=None, description="Room IDs to assign (required for room_admin)")


# Response schemas
class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    industry: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    role_label: str
    auth_provider: Optional[str] = "email"
    created_at: datetime

    model_config = {"from_attributes": True}


class UserWithOrgResponse(BaseModel):
    id: UUID
    email: str
    name: str
    role: str
    role_label: str
    auth_provider: Optional[str] = "email"
    created_at: datetime
    organization: OrganizationResponse

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
    organization: OrganizationResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LogoutRequest(BaseModel):
    access_token: Optional[str] = None
    revoke_all: bool = False  # Revoke all refresh tokens


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class TokenPayload(BaseModel):
    sub: str  # user_id
    org_id: str
    exp: Optional[datetime] = None
    jti: Optional[str] = None  # JWT ID for blacklisting
    type: Optional[str] = None  # 'access' or 'refresh'


# Google OAuth schemas
class GoogleAuthRequest(BaseModel):
    credential: str  # Google ID token JWT from @react-oauth/google


class GoogleOrgSetupRequest(BaseModel):
    google_token: str  # Short-lived setup token from /api/auth/google
    org_name: str = Field(..., min_length=2, max_length=100)
    industry: Optional[str] = Field(None, max_length=100)


class GoogleAuthResponse(BaseModel):
    needs_setup: bool = False
    setup_token: Optional[str] = None
    google_name: Optional[str] = None
    google_email: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[UserResponse] = None
    organization: Optional[OrganizationResponse] = None
