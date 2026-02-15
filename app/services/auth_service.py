import secrets
import string
from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    store_refresh_token,
    validate_refresh_token,
    rotate_refresh_token,
    revoke_all_user_tokens,
    create_google_setup_token,
)
from app.models import Organization, User, UserRoomAssignment
from app.schemas.auth import RegisterOrgRequest, InviteUserRequest


MIN_PASSWORD_LENGTH = 8


def validate_password_strength(password: str) -> None:
    """Validate password meets minimum requirements. Raises ValueError if weak."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if not any(c.isupper() for c in password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one number")


class AuthService:
    """Service for handling authentication business logic."""

    @staticmethod
    def generate_temp_password(length: int = 12) -> str:
        """Generate a temporary password for invited users."""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        """Get a user by email address."""
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def get_user_by_id(db: Session, user_id: UUID) -> Optional[User]:
        """Get a user by ID."""
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_organization_by_id(db: Session, org_id: UUID) -> Optional[Organization]:
        """Get an organization by ID."""
        return db.query(Organization).filter(Organization.id == org_id).first()

    @staticmethod
    def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
        """Authenticate a user by email and password."""
        user = AuthService.get_user_by_email(db, email)
        if not user:
            return None
        if not user.password_hash:
            return None  # Google-only users cannot use password login
        if not verify_password(password, user.password_hash):
            return None
        return user

    @staticmethod
    def create_organization(db: Session, name: str, industry: Optional[str] = None) -> Organization:
        """Create a new organization."""
        org = Organization(name=name, industry=industry)
        db.add(org)
        db.flush()  # Get the ID without committing
        return org

    @staticmethod
    def create_user(
        db: Session,
        org_id: UUID,
        email: str,
        password: str,
        name: str,
        role_label: str,
        role: str = "admin",
    ) -> User:
        """Create a new user."""
        user = User(
            org_id=org_id,
            email=email,
            password_hash=get_password_hash(password),
            name=name,
            role=role,
            role_label=role_label,
        )
        db.add(user)
        db.flush()
        return user

    @staticmethod
    def register_organization(
        db: Session, data: RegisterOrgRequest
    ) -> tuple[Organization, User, str, str]:
        """
        Register a new organization with its first admin user.
        Returns the organization, user, access token, and refresh token.
        """
        # Validate password strength
        validate_password_strength(data.admin_password)

        # Check if email already exists
        existing_user = AuthService.get_user_by_email(db, data.admin_email)
        if existing_user:
            raise ValueError("Email already registered")

        # Create organization
        org = AuthService.create_organization(db, data.org_name, data.industry)

        # Create admin user
        user = AuthService.create_user(
            db=db,
            org_id=org.id,
            email=data.admin_email,
            password=data.admin_password,
            name=data.admin_name,
            role_label="Admin",
        )

        db.commit()
        db.refresh(org)
        db.refresh(user)

        # Create tokens
        token_data = {"sub": str(user.id), "org_id": str(org.id)}
        access_token = create_access_token(data=token_data)
        refresh_token, expires_at = create_refresh_token(data=token_data)

        # Store refresh token
        store_refresh_token(db, str(user.id), refresh_token, expires_at)

        return org, user, access_token, refresh_token

    @staticmethod
    def login(
        db: Session, email: str, password: str
    ) -> tuple[User, Organization, str, str]:
        """
        Authenticate user and return user, org, access token, and refresh token.
        Raises ValueError if authentication fails.
        """
        user = AuthService.authenticate_user(db, email, password)
        if not user:
            raise ValueError("Invalid email or password")

        org = AuthService.get_organization_by_id(db, user.org_id)
        if not org:
            raise ValueError("Organization not found")

        # Create tokens
        token_data = {"sub": str(user.id), "org_id": str(org.id)}
        access_token = create_access_token(data=token_data)
        refresh_token, expires_at = create_refresh_token(data=token_data)

        # Store refresh token
        store_refresh_token(db, str(user.id), refresh_token, expires_at)

        return user, org, access_token, refresh_token

    @staticmethod
    def refresh_tokens(
        db: Session, user_id: str, old_refresh_token: str
    ) -> tuple[str, str]:
        """
        Refresh tokens using token rotation.
        Returns new access token and refresh token.
        """
        # Validate the old refresh token
        if not validate_refresh_token(db, old_refresh_token):
            raise ValueError("Invalid or expired refresh token")

        # Get user and org
        user = AuthService.get_user_by_id(db, UUID(user_id))
        if not user:
            raise ValueError("User not found")

        org = AuthService.get_organization_by_id(db, user.org_id)
        if not org:
            raise ValueError("Organization not found")

        # Rotate refresh token
        new_refresh_token, _ = rotate_refresh_token(db, old_refresh_token, user_id)

        # Create new access token
        token_data = {"sub": str(user.id), "org_id": str(org.id)}
        new_access_token = create_access_token(data=token_data)

        return new_access_token, new_refresh_token

    @staticmethod
    def invite_user(
        db: Session,
        org_id: UUID,
        data: InviteUserRequest,
        invited_by: UUID,
    ) -> tuple[User, str]:
        """
        Invite a new user to an organization.
        Returns the user and temporary password.
        """
        # Check if email already exists in this org
        existing_user = db.query(User).filter(
            User.org_id == org_id,
            User.email == data.email
        ).first()

        if existing_user:
            raise ValueError("User with this email already exists in the organization")

        # Validate room_admin has room assignments
        if data.role == "room_admin" and not data.room_ids:
            raise ValueError("Room assignments are required for room_admin role")

        # Generate temporary password
        temp_password = AuthService.generate_temp_password()

        # Create user
        user = AuthService.create_user(
            db=db,
            org_id=org_id,
            email=data.email,
            password=temp_password,
            name=data.name,
            role_label=data.role_label,
            role=data.role,
        )

        # Create room assignments for room_admin
        if data.role == "room_admin" and data.room_ids:
            AuthService.assign_rooms_to_user(db, user.id, data.room_ids, invited_by, org_id)

        db.commit()
        db.refresh(user)

        return user, temp_password

    @staticmethod
    def assign_rooms_to_user(
        db: Session,
        user_id: UUID,
        room_ids: List[UUID],
        assigned_by: UUID,
        org_id: UUID,
    ) -> List[UserRoomAssignment]:
        """Assign rooms to a user."""
        from app.models import Room

        assignments = []
        for room_id in room_ids:
            # Verify room exists and belongs to org
            room = db.query(Room).filter(
                Room.id == room_id,
                Room.org_id == org_id
            ).first()
            if not room:
                raise ValueError(f"Room {room_id} not found")

            assignment = UserRoomAssignment(
                user_id=user_id,
                room_id=room_id,
                assigned_by=assigned_by,
            )
            db.add(assignment)
            assignments.append(assignment)

        return assignments

    @staticmethod
    def change_password(
        db: Session,
        user: User,
        current_password: str,
        new_password: str,
    ) -> bool:
        """Change user's password after verifying current password."""
        if not user.password_hash:
            raise ValueError("Password login is not enabled for this account. Sign in with Google instead.")
        if not verify_password(current_password, user.password_hash):
            raise ValueError("Current password is incorrect")
        validate_password_strength(new_password)

        user.password_hash = get_password_hash(new_password)

        # Revoke all existing refresh tokens so old sessions can't be reused
        revoke_all_user_tokens(db, str(user.id))

        db.commit()
        return True

    @staticmethod
    def reset_password(db: Session, user_id: UUID) -> str:
        """Reset a user's password to a new temporary password (Admin only)."""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")

        temp_password = AuthService.generate_temp_password()
        user.password_hash = get_password_hash(temp_password)

        # Revoke all existing refresh tokens for the reset user
        revoke_all_user_tokens(db, str(user_id))

        db.commit()
        return temp_password

    @staticmethod
    def google_authenticate(
        db: Session, google_info: dict
    ) -> tuple:
        """
        Handle Google OAuth authentication.
        Returns (True, user, org, access_token, refresh_token) for existing users,
        or (False, setup_token, google_name, google_email) for new users needing org setup.
        """
        email = google_info["email"].lower()
        google_sub = google_info["sub"]

        # Case 1: Find user by google_id (returning Google user)
        user = db.query(User).filter(User.google_id == google_sub).first()
        if user:
            org = AuthService.get_organization_by_id(db, user.org_id)
            token_data = {"sub": str(user.id), "org_id": str(org.id)}
            access_token = create_access_token(data=token_data)
            refresh_token, expires_at = create_refresh_token(data=token_data)
            store_refresh_token(db, str(user.id), refresh_token, expires_at)
            return (True, user, org, access_token, refresh_token)

        # Case 2: Find user by email (existing email/password user → link accounts)
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.google_id = google_sub
            user.auth_provider = "both"
            db.commit()
            db.refresh(user)

            org = AuthService.get_organization_by_id(db, user.org_id)
            token_data = {"sub": str(user.id), "org_id": str(org.id)}
            access_token = create_access_token(data=token_data)
            refresh_token, expires_at = create_refresh_token(data=token_data)
            store_refresh_token(db, str(user.id), refresh_token, expires_at)
            return (True, user, org, access_token, refresh_token)

        # Case 3: New user — needs org setup
        setup_token = create_google_setup_token(google_info)
        return (False, setup_token, google_info.get("name", ""), email)

    @staticmethod
    def google_complete_setup(
        db: Session,
        google_sub: str,
        email: str,
        name: str,
        org_name: str,
        industry: Optional[str] = None,
    ) -> tuple[Organization, User, str, str]:
        """
        Create org + user for a new Google sign-in user.
        Returns (org, user, access_token, refresh_token).
        """
        existing_user = AuthService.get_user_by_email(db, email)
        if existing_user:
            raise ValueError("Email already registered")

        org = Organization(name=org_name, industry=industry)
        db.add(org)
        db.flush()

        user = User(
            org_id=org.id,
            email=email,
            password_hash=None,
            name=name,
            role="admin",
            role_label="Admin",
            google_id=google_sub,
            auth_provider="google",
        )
        db.add(user)
        db.flush()

        db.commit()
        db.refresh(org)
        db.refresh(user)

        token_data = {"sub": str(user.id), "org_id": str(org.id)}
        access_token = create_access_token(data=token_data)
        refresh_token, expires_at = create_refresh_token(data=token_data)
        store_refresh_token(db, str(user.id), refresh_token, expires_at)

        return org, user, access_token, refresh_token
