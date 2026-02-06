from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user_org
from app.models import User, Organization
from app.schemas.kpi import (
    KPICreateRequest,
    KPIUpdateRequest,
    KPIResponse,
    KPIWithDataResponse,
    KPIListResponse,
    SeedPresetsResponse,
    SeedPresetsRequest,
    AvailablePresetsResponse,
    PresetInfo,
)
from app.schemas.entries import DataEntryResponse
from app.services.kpi_service import KPIService


router = APIRouter(prefix="/kpis", tags=["KPIs"])


@router.get("", response_model=KPIListResponse)
def get_all_kpis(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get all KPIs for the current user's organization.
    Includes both preset and custom KPIs.
    """
    _, org = user_org
    kpis = KPIService.get_all_kpis(db, org.id)

    return KPIListResponse(
        kpis=[KPIResponse.model_validate(kpi) for kpi in kpis],
        total=len(kpis),
    )


@router.post("", response_model=KPIResponse, status_code=status.HTTP_201_CREATED)
def create_kpi(
    data: KPICreateRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Create a new custom KPI.
    Formula syntax is validated before saving.
    """
    import logging
    logger = logging.getLogger(__name__)

    user, org = user_org

    # Check if name already exists
    if KPIService.check_kpi_name_exists(db, org.id, data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A KPI with this name already exists",
        )

    try:
        kpi = KPIService.create_kpi(db, org.id, user.id, data)
        return KPIResponse.model_validate(kpi)
    except Exception as e:
        logger.error(f"Failed to create KPI: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create KPI: {str(e)}",
        )


# Static routes must come BEFORE dynamic /{kpi_id} routes
@router.get("/available-presets", response_model=AvailablePresetsResponse)
def get_available_presets(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get list of available preset KPIs that haven't been added yet.
    """
    _, org = user_org

    available = KPIService.get_available_presets(db, org.id)

    return AvailablePresetsResponse(
        available_presets=[PresetInfo(**p) for p in available],
        total=len(available),
    )


@router.post("/seed-presets", response_model=SeedPresetsResponse)
def seed_presets(
    data: SeedPresetsRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Seed selected KPI presets for the organization.
    Only adds the presets specified in preset_names.
    """
    _, org = user_org

    created_presets = KPIService.seed_presets(db, org.id, data.preset_names)

    return SeedPresetsResponse(
        message=f"Successfully seeded {len(created_presets)} preset KPIs",
        presets_created=len(created_presets),
        presets=[KPIResponse.model_validate(p) for p in created_presets],
    )


# Dynamic routes with path parameters
@router.get("/{kpi_id}", response_model=KPIWithDataResponse)
def get_kpi(
    kpi_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get a single KPI with its recent data entries.
    """
    _, org = user_org

    result = KPIService.get_kpi_with_data(db, kpi_id, org.id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KPI not found",
        )

    kpi, entries = result
    return KPIWithDataResponse(
        kpi=KPIResponse.model_validate(kpi),
        recent_entries=[DataEntryResponse.model_validate(e) for e in entries],
    )


@router.put("/{kpi_id}", response_model=KPIResponse)
def update_kpi(
    kpi_id: UUID,
    data: KPIUpdateRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Update an existing KPI.
    Only custom KPIs can be modified (not presets).
    """
    _, org = user_org

    kpi = KPIService.get_kpi_by_id(db, kpi_id, org.id)
    if not kpi:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KPI not found",
        )

    # Check name uniqueness if updating name
    if data.name and KPIService.check_kpi_name_exists(db, org.id, data.name, exclude_id=kpi_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A KPI with this name already exists",
        )

    try:
        updated_kpi = KPIService.update_kpi(db, kpi, data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return KPIResponse.model_validate(updated_kpi)


@router.delete("/{kpi_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kpi(
    kpi_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Delete a KPI.
    Only custom KPIs can be deleted (not presets).
    Historical data entries will also be removed.
    """
    _, org = user_org

    kpi = KPIService.get_kpi_by_id(db, kpi_id, org.id)
    if not kpi:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KPI not found",
        )

    try:
        KPIService.delete_kpi(db, kpi)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return None
