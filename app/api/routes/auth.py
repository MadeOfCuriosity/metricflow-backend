from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user, get_current_user_org, require_admin_org
from app.models import User, Organization
from app.schemas.auth import (
    RegisterOrgRequest,
    LoginRequest,
    InviteUserRequest,
    AuthResponse,
    UserResponse,
    UserWithOrgResponse,
    OrganizationResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    LogoutRequest,
    ChangePasswordRequest,
    GoogleAuthRequest,
    GoogleOrgSetupRequest,
    GoogleAuthResponse,
)
from app.services.auth_service import AuthService
from app.core.rate_limit import limiter, public_limiter
from app.core.security import (
    verify_token,
    is_token_blacklisted,
    blacklist_token,
    rotate_refresh_token,
    revoke_all_user_tokens,
    verify_google_id_token,
    TOKEN_TYPE_REFRESH,
    TOKEN_TYPE_SETUP,
)
from app.core.sanitization import sanitize_email, sanitize_name, validate_email
from datetime import datetime


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register-org", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")  # Strict rate limit for registration
def register_organization(
    request: Request,
    data: RegisterOrgRequest,
    db: Session = Depends(get_db),
):
    """
    Register a new organization with the first admin user.
    Returns JWT token and user/org info.
    """
    # Sanitize inputs
    data.admin_email = sanitize_email(data.admin_email)
    data.admin_name = sanitize_name(data.admin_name)
    data.org_name = sanitize_name(data.org_name)

    # Validate email format
    if not validate_email(data.admin_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format",
        )

    try:
        org, user, access_token, refresh_token = AuthService.register_organization(db, data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
        organization=OrganizationResponse.model_validate(org),
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")  # Strict rate limit for login
def login(
    request: Request,
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Authenticate user and return JWT token.
    """
    # Sanitize email input
    email = sanitize_email(data.email)

    try:
        user, org, access_token, refresh_token = AuthService.login(db, email, data.password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
        organization=OrganizationResponse.model_validate(org),
    )


@router.post("/google", response_model=GoogleAuthResponse)
@limiter.limit("10/minute")
def google_auth(
    request: Request,
    data: GoogleAuthRequest,
    db: Session = Depends(get_db),
):
    """Authenticate with Google ID token."""
    from app.core.config import settings

    google_info = verify_google_id_token(data.credential, settings.GOOGLE_OAUTH_CLIENT_ID)
    if not google_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google credential",
        )

    result = AuthService.google_authenticate(db, google_info)

    if result[0]:  # Existing user
        _, user, org, access_token, refresh_token = result
        return GoogleAuthResponse(
            needs_setup=False,
            access_token=access_token,
            refresh_token=refresh_token,
            user=UserResponse.model_validate(user),
            organization=OrganizationResponse.model_validate(org),
        )
    else:  # New user needs org setup
        _, setup_token, google_name, google_email = result
        return GoogleAuthResponse(
            needs_setup=True,
            setup_token=setup_token,
            google_name=google_name,
            google_email=google_email,
        )


@router.post("/google/complete-setup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def google_complete_setup(
    request: Request,
    data: GoogleOrgSetupRequest,
    db: Session = Depends(get_db),
):
    """Complete organization setup for a new Google user."""
    payload = verify_token(data.google_token, expected_type=TOKEN_TYPE_SETUP)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired setup token. Please sign in with Google again.",
        )

    google_sub = payload["google_sub"]
    email = sanitize_email(payload["email"])
    name = sanitize_name(payload.get("name", email.split("@")[0]))
    org_name = sanitize_name(data.org_name)

    try:
        org, user, access_token, refresh_token = AuthService.google_complete_setup(
            db, google_sub, email, name, org_name, data.industry
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
        organization=OrganizationResponse.model_validate(org),
    )


@router.post("/invite-user", response_model=dict, status_code=status.HTTP_201_CREATED)
def invite_user(
    data: InviteUserRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    Invite a new user to the organization.
    Only admins can invite others to their org.
    Returns user info and temporary password.
    """
    admin_user, org = admin_org

    # Sanitize inputs
    data.email = sanitize_email(data.email)
    data.name = sanitize_name(data.name)

    try:
        new_user, temp_password = AuthService.invite_user(db, org.id, data, admin_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return {
        "user": UserResponse.model_validate(new_user),
        "temporary_password": temp_password,
        "message": "User invited successfully. Share the temporary password securely.",
    }


@router.get("/me", response_model=UserWithOrgResponse)
def get_current_user_info(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
):
    """
    Get current authenticated user's info including organization.
    """
    current_user, org = user_org

    return UserWithOrgResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        role=current_user.role,
        role_label=current_user.role_label,
        created_at=current_user.created_at,
        organization=OrganizationResponse.model_validate(org),
    )


@router.post("/refresh", response_model=RefreshTokenResponse)
@limiter.limit("30/minute")
def refresh_access_token(
    request: Request,
    data: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """
    Refresh access token using a valid refresh token.
    Implements token rotation - returns new refresh token.
    """
    # Verify the refresh token
    payload = verify_token(data.refresh_token, expected_type=TOKEN_TYPE_REFRESH)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Check if token is blacklisted
    jti = payload.get("jti")
    if jti and is_token_blacklisted(db, jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    # Rotate the refresh token
    try:
        new_access_token, new_refresh_token = AuthService.refresh_tokens(
            db, user_id, data.refresh_token
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    return RefreshTokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )


@router.post("/logout")
def logout(
    data: LogoutRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Logout user by blacklisting the current access token.
    Optionally revoke all refresh tokens.
    """
    current_user, _ = user_org

    # Blacklist the access token if provided
    if data.access_token:
        payload = verify_token(data.access_token)
        if payload and payload.get("jti"):
            exp = payload.get("exp")
            expires_at = datetime.fromtimestamp(exp) if exp else datetime.utcnow()
            blacklist_token(
                db,
                jti=payload["jti"],
                user_id=str(current_user.id),
                token_type="access",
                expires_at=expires_at,
            )

    # Revoke all refresh tokens if requested
    if data.revoke_all:
        revoke_all_user_tokens(db, str(current_user.id))

    return {"message": "Logged out successfully"}


@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change the current user's password.
    Requires current password verification.
    """
    try:
        AuthService.change_password(db, current_user, data.current_password, data.new_password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return {"message": "Password updated successfully"}
