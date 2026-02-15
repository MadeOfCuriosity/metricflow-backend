from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user_org, require_admin_org, check_room_access
from app.models import User, Organization, Room as RoomModel
from app.schemas.kpi import KPIResponse
from app.schemas.rooms import (
    RoomCreateRequest,
    RoomUpdateRequest,
    RoomResponse,
    RoomListResponse,
    RoomTreeResponse,
    RoomTreeNode,
    AssignKPIsRequest,
    AssignKPIsResponse,
    RoomDashboardResponse,
    RoomBreadcrumb,
)
from app.services.room_service import RoomService


router = APIRouter(prefix="/rooms", tags=["Rooms"])


@router.get("", response_model=RoomListResponse)
def get_all_rooms(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get all rooms for the current user's organization (flat list).
    Admins see all rooms, room_admins see only assigned rooms.
    """
    user, org = user_org
    rooms = RoomService.get_accessible_rooms(db, org.id, user)

    room_responses = []
    for room in rooms:
        room_data = RoomService.get_room_with_counts(db, room)
        room_responses.append(RoomResponse(**room_data))

    return RoomListResponse(
        rooms=room_responses,
        total=len(room_responses),
    )


@router.get("/tree", response_model=RoomTreeResponse)
def get_room_tree(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get rooms as a nested tree structure for sidebar display.
    Admins see full tree, room_admins see only assigned rooms.
    """
    user, org = user_org
    tree = RoomService.get_room_tree(db, org.id, user)

    def dict_to_tree_node(d: dict) -> RoomTreeNode:
        return RoomTreeNode(
            id=d["id"],
            name=d["name"],
            description=d["description"],
            children=[dict_to_tree_node(c) for c in d["children"]],
            kpi_count=d["kpi_count"],
        )

    return RoomTreeResponse(
        rooms=[dict_to_tree_node(r) for r in tree],
    )


@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
def create_room(
    data: RoomCreateRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    Create a new room (Admin only).
    """
    user, org = admin_org

    # Check if name already exists at the same level
    if RoomService.check_room_name_exists(db, org.id, data.name, data.parent_room_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A room with this name already exists at this level",
        )

    try:
        room = RoomService.create_room(db, org.id, user.id, data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    room_data = RoomService.get_room_with_counts(db, room)
    return RoomResponse(**room_data)


@router.get("/{room_id}", response_model=RoomResponse)
def get_room(
    room_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get a single room by ID.
    """
    user, org = user_org

    room = RoomService.get_room_by_id(db, room_id, org.id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )

    # Check access for room_admin
    if not check_room_access(room_id, user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this room",
        )

    room_data = RoomService.get_room_with_counts(db, room)
    return RoomResponse(**room_data)


@router.put("/{room_id}", response_model=RoomResponse)
def update_room(
    room_id: UUID,
    data: RoomUpdateRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """
    Update an existing room (Admin only).
    """
    _, org = admin_org

    room = RoomService.get_room_by_id(db, room_id, org.id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )

    # Check name uniqueness if updating name
    if data.name and RoomService.check_room_name_exists(
        db, org.id, data.name, room.parent_room_id, exclude_id=room_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A room with this name already exists at this level",
        )

    updated_room = RoomService.update_room(db, room, data)
    room_data = RoomService.get_room_with_counts(db, updated_room)
    return RoomResponse(**room_data)


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room(
    room_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Delete a room.
    Admins can delete any room.
    Room admins can only delete sub-rooms within their assigned rooms, not the assigned rooms themselves.
    """
    user, org = user_org

    room = RoomService.get_room_by_id(db, room_id, org.id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )

    # Only leaf rooms (no children) can be deleted
    child_count = db.query(RoomModel).filter(RoomModel.parent_room_id == room.id).count()
    if child_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a room that has sub-rooms. Delete the sub-rooms first.",
        )

    if user.role != "admin":
        # Room admins can only delete sub-rooms (rooms with a parent)
        if room.parent_room_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can delete top-level rooms",
            )

        # Check the room admin has access to the parent room
        if not check_room_access(room.parent_room_id, user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this room",
            )

    RoomService.delete_room(db, room)
    return None


@router.post("/{room_id}/kpis", response_model=AssignKPIsResponse)
def assign_kpis_to_room(
    room_id: UUID,
    data: AssignKPIsRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Assign KPIs to a room.
    Admins can assign to any room, room_admins can only assign to their rooms.
    """
    user, org = user_org

    room = RoomService.get_room_by_id(db, room_id, org.id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )

    # Check access for room_admin
    if not check_room_access(room_id, user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this room",
        )

    assignments = RoomService.assign_kpis_to_room(db, room, data.kpi_ids, user.id, org.id)

    return AssignKPIsResponse(
        message=f"Successfully assigned {len(assignments)} KPIs to room",
        assigned_count=len(assignments),
    )


@router.delete("/{room_id}/kpis/{kpi_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_kpi_from_room(
    room_id: UUID,
    kpi_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Remove a KPI from a room.
    Admins can remove from any room, room_admins can only remove from their rooms.
    """
    user, org = user_org

    room = RoomService.get_room_by_id(db, room_id, org.id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )

    # Check access for room_admin
    if not check_room_access(room_id, user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this room",
        )

    removed = RoomService.remove_kpi_from_room(db, room, kpi_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KPI not assigned to this room",
        )

    return None


@router.get("/{room_id}/dashboard", response_model=RoomDashboardResponse)
def get_room_dashboard(
    room_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get room dashboard data including room-specific and shared KPIs.
    """
    user, org = user_org

    room = RoomService.get_room_by_id(db, room_id, org.id)
    if not room:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )

    # Check access for room_admin
    if not check_room_access(room_id, user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this room",
        )

    # Get room data with counts
    room_data = RoomService.get_room_with_counts(db, room)

    # Get ancestors for breadcrumbs
    ancestors = RoomService.get_ancestors(db, room)
    breadcrumbs = [
        RoomBreadcrumb(id=a.id, name=a.name) for a in ancestors
    ]
    breadcrumbs.append(RoomBreadcrumb(id=room.id, name=room.name))

    # Get KPIs (all rooms get descendant KPIs rolled up)
    room_kpis, sub_room_kpis, shared_kpis = RoomService.get_room_kpis(
        db, room_id, org.id
    )

    return RoomDashboardResponse(
        room=RoomResponse(**room_data),
        breadcrumbs=breadcrumbs,
        room_kpis=[KPIResponse.model_validate(k) for k in room_kpis],
        sub_room_kpis=[KPIResponse.model_validate(k) for k in sub_room_kpis],
        shared_kpis=[KPIResponse.model_validate(k) for k in shared_kpis],
    )
