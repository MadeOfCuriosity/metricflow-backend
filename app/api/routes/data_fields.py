from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user_org, check_room_access
from app.models import User, Organization, KPIDataField, KPIDefinition
from app.schemas.data_fields import (
    DataFieldCreateRequest,
    DataFieldUpdateRequest,
    DataFieldResponse,
    DataFieldListResponse,
)
from app.schemas.kpi import KPIResponse
from app.services.data_field_service import DataFieldService


router = APIRouter(prefix="/data-fields", tags=["Data Fields"])


@router.get("", response_model=DataFieldListResponse)
def list_data_fields(
    room_id: Optional[UUID] = Query(None, description="Filter by room ID"),
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    List data fields accessible to the current user.
    Admin: all fields. Room admin: fields in assigned rooms + sub-rooms.
    """
    user, org = user_org

    if room_id:
        fields = DataFieldService.get_all_data_fields(db, org.id, room_id=room_id)
    else:
        fields = DataFieldService.get_accessible_data_fields(
            db, org.id, user.role, user.id
        )

    enriched = DataFieldService.enrich_with_metadata(db, fields)

    return DataFieldListResponse(
        data_fields=[DataFieldResponse(**f) for f in enriched],
        total=len(enriched),
    )


@router.get("/{field_id}", response_model=DataFieldResponse)
def get_data_field(
    field_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """Get a single data field with metadata."""
    _, org = user_org

    field = DataFieldService.get_data_field_by_id(db, field_id, org.id)
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data field not found",
        )

    enriched = DataFieldService.enrich_with_metadata(db, [field])
    return DataFieldResponse(**enriched[0])


@router.post("", response_model=DataFieldResponse, status_code=status.HTTP_201_CREATED)
def create_data_field(
    data: DataFieldCreateRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Create a new data field.
    Admin: can assign to any room. Room admin: can only assign to their rooms.
    """
    user, org = user_org

    # If room_id is specified, check access
    if data.room_id:
        if not check_room_access(data.room_id, user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this room",
            )

    field = DataFieldService.create_data_field(db, org.id, user.id, data)
    enriched = DataFieldService.enrich_with_metadata(db, [field])
    return DataFieldResponse(**enriched[0])


@router.put("/{field_id}", response_model=DataFieldResponse)
def update_data_field(
    field_id: UUID,
    data: DataFieldUpdateRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """Update a data field. variable_name is immutable."""
    user, org = user_org

    # Only admins can update data fields
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to update data fields",
        )

    field = DataFieldService.get_data_field_by_id(db, field_id, org.id)
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data field not found",
        )

    # If changing room_id, verify access
    if data.room_id and not check_room_access(data.room_id, user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to the target room",
        )

    field = DataFieldService.update_data_field(db, field, data)
    enriched = DataFieldService.enrich_with_metadata(db, [field])
    return DataFieldResponse(**enriched[0])


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_data_field(
    field_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """Delete a data field. Only allowed if no KPIs reference it."""
    user, org = user_org

    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to delete data fields",
        )

    field = DataFieldService.get_data_field_by_id(db, field_id, org.id)
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data field not found",
        )

    try:
        DataFieldService.delete_data_field(db, field)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    return None


@router.get("/{field_id}/kpis")
def get_data_field_kpis(
    field_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """Get KPIs that use this data field."""
    _, org = user_org

    field = DataFieldService.get_data_field_by_id(db, field_id, org.id)
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data field not found",
        )

    # Get KPIs via the join table
    kpi_links = db.query(KPIDataField).filter(
        KPIDataField.data_field_id == field_id
    ).all()

    kpis = []
    for link in kpi_links:
        kpi = db.query(KPIDefinition).filter(
            KPIDefinition.id == link.kpi_id
        ).first()
        if kpi:
            kpis.append(KPIResponse.model_validate(kpi))

    return {"kpis": kpis, "total": len(kpis)}
