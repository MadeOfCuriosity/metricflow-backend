from typing import Generator, Callable
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import verify_token
from app.models import User, Organization, UserRoomAssignment
from app.models.room import Room


# HTTP Bearer token scheme
security = HTTPBearer()


def get_db() -> Generator:
    """Database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency to get the current authenticated user from JWT token.
    Raises HTTPException if token is invalid or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise credentials_exception

    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    try:
        user = db.query(User).filter(User.id == UUID(user_id)).first()
    except (ValueError, JWTError):
        raise credentials_exception

    if user is None:
        raise credentials_exception

    return user


def get_current_user_org(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> tuple[User, Organization]:
    """
    Dependency to get current user and their organization.
    Raises HTTPException if organization not found.
    """
    org = db.query(Organization).filter(Organization.id == current_user.org_id).first()

    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return current_user, org


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency to require admin role.
    Raises HTTPException if user is not an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def require_admin_org(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> tuple[User, Organization]:
    """
    Dependency to require admin role and get organization.
    """
    org = db.query(Organization).filter(Organization.id == current_user.org_id).first()

    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return current_user, org


def check_room_access(
    room_id: UUID,
    current_user: User,
    db: Session,
) -> bool:
    """
    Check if user has access to a specific room.
    Admins have access to all rooms.
    Room admins have access to assigned rooms AND their sub-rooms.
    """
    if current_user.role == "admin":
        return True

    # Check if room_admin has direct access to this room
    assignment = db.query(UserRoomAssignment).filter(
        UserRoomAssignment.user_id == current_user.id,
        UserRoomAssignment.room_id == room_id
    ).first()

    if assignment:
        return True

    # Check if this room is a sub-room of an assigned room
    room = db.query(Room).filter(Room.id == room_id).first()
    if room and room.parent_room_id:
        parent_assignment = db.query(UserRoomAssignment).filter(
            UserRoomAssignment.user_id == current_user.id,
            UserRoomAssignment.room_id == room.parent_room_id
        ).first()
        if parent_assignment:
            return True

    return False


def get_user_accessible_room_ids(
    current_user: User,
    db: Session,
) -> list[UUID] | None:
    """
    Get list of room IDs the user has access to.
    Returns None for admins (meaning all rooms).
    Returns list of assigned room IDs + their sub-room IDs for room_admins.
    """
    if current_user.role == "admin":
        return None  # Admins have access to all rooms

    assignments = db.query(UserRoomAssignment.room_id).filter(
        UserRoomAssignment.user_id == current_user.id
    ).all()

    assigned_ids = [a.room_id for a in assignments]

    # Also include sub-rooms of assigned rooms
    sub_rooms = db.query(Room.id).filter(
        Room.parent_room_id.in_(assigned_ids)
    ).all()

    return assigned_ids + [s.id for s in sub_rooms]
