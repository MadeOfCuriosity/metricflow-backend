from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin_org
from app.models import User, Organization
from app.schemas.users import (
    UserWithRoomsResponse,
    UserListResponse,
    UpdateUserRoomsRequest,
    UpdateUserRoleRequest,
    RoomBasicResponse,
)
from app.services.user_service import UserService
from app.services.auth_service import AuthService


router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=UserListResponse)
def get_all_users(
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    Get all users in the organization (Admin only).
    """
    _, org = admin_org
    users_data = UserService.get_users_with_rooms(db, org.id)

    users = []
    for user_data in users_data:
        users.append(UserWithRoomsResponse(
            id=user_data["id"],
            email=user_data["email"],
            name=user_data["name"],
            role=user_data["role"],
            role_label=user_data["role_label"],
            created_at=user_data["created_at"],
            assigned_rooms=[RoomBasicResponse(**r) for r in user_data["assigned_rooms"]],
        ))

    return UserListResponse(users=users, total=len(users))


@router.get("/{user_id}", response_model=UserWithRoomsResponse)
def get_user(
    user_id: UUID,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    Get a single user with their room assignments (Admin only).
    """
    _, org = admin_org
    user_data = UserService.get_user_with_rooms(db, user_id)

    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Verify user belongs to the same org
    user = UserService.get_user_by_id(db, user_id, org.id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserWithRoomsResponse(
        id=user_data["id"],
        email=user_data["email"],
        name=user_data["name"],
        role=user_data["role"],
        role_label=user_data["role_label"],
        created_at=user_data["created_at"],
        assigned_rooms=[RoomBasicResponse(**r) for r in user_data["assigned_rooms"]],
    )


@router.put("/{user_id}/rooms", response_model=UserWithRoomsResponse)
def update_user_rooms(
    user_id: UUID,
    data: UpdateUserRoomsRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    Update a user's room assignments (Admin only).
    """
    admin_user, org = admin_org

    # Cannot modify own rooms
    if user_id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify your own room assignments",
        )

    try:
        UserService.assign_rooms_to_user(db, user_id, data.room_ids, admin_user.id, org.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    user_data = UserService.get_user_with_rooms(db, user_id)
    return UserWithRoomsResponse(
        id=user_data["id"],
        email=user_data["email"],
        name=user_data["name"],
        role=user_data["role"],
        role_label=user_data["role_label"],
        created_at=user_data["created_at"],
        assigned_rooms=[RoomBasicResponse(**r) for r in user_data["assigned_rooms"]],
    )


@router.put("/{user_id}/role", response_model=UserWithRoomsResponse)
def update_user_role(
    user_id: UUID,
    data: UpdateUserRoleRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    Update a user's role (Admin only).
    """
    admin_user, org = admin_org

    # Cannot modify own role
    if user_id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify your own role",
        )

    try:
        UserService.update_user_role(db, user_id, data.role, data.room_ids, admin_user.id, org.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    user_data = UserService.get_user_with_rooms(db, user_id)
    return UserWithRoomsResponse(
        id=user_data["id"],
        email=user_data["email"],
        name=user_data["name"],
        role=user_data["role"],
        role_label=user_data["role_label"],
        created_at=user_data["created_at"],
        assigned_rooms=[RoomBasicResponse(**r) for r in user_data["assigned_rooms"]],
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    Delete a user from the organization (Admin only).
    """
    admin_user, org = admin_org

    # Cannot delete self
    if user_id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )

    deleted = UserService.delete_user(db, user_id, org.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return None


@router.post("/{user_id}/reset-password")
def reset_user_password(
    user_id: UUID,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    Reset a user's password to a new temporary password (Admin only).
    Returns the new temporary password.
    """
    admin_user, org = admin_org

    # Verify user belongs to the same org
    user = UserService.get_user_by_id(db, user_id, org.id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    try:
        temp_password = AuthService.reset_password(db, user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return {
        "temporary_password": temp_password,
        "message": "Password has been reset. Share the new temporary password securely.",
    }
