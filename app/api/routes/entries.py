from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user_org
from app.models import User, Organization
from app.schemas.entries import (
    CreateEntriesRequest,
    CreateEntriesResponse,
    DataEntryResponse,
    EntryListResponse,
    KPIFormItem,
    TodayFormResponse,
    StatsSummaryResponse,
)
from app.schemas.data_fields import (
    CreateFieldEntriesRequest,
    CreateFieldEntriesResponse,
    FieldEntryResponse,
    RoomFieldGroup,
    FieldFormItem,
    TodayFieldFormResponse,
)
from app.services.entry_service import EntryService


router = APIRouter(prefix="/entries", tags=["Data Entries"])


@router.post("", response_model=CreateEntriesResponse, status_code=status.HTTP_201_CREATED)
def create_entries(
    data: CreateEntriesRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Submit daily data for one or more KPIs.
    Auto-calculates the KPI result using the formula.
    If an entry already exists for the date, it will be updated.
    """
    user, org = user_org

    created_entries, errors = EntryService.create_entries(
        db=db,
        org_id=org.id,
        user_id=user.id,
        entry_date=data.date,
        entries=data.entries,
    )

    # Get KPI names for response
    entry_responses = []
    for entry in created_entries:
        response = DataEntryResponse(
            id=entry.id,
            kpi_id=entry.kpi_id,
            kpi_name=entry.kpi_definition.name if entry.kpi_definition else None,
            date=entry.date,
            values=entry.values,
            calculated_value=entry.calculated_value,
            entered_by=entry.entered_by,
            created_at=entry.created_at,
        )
        entry_responses.append(response)

    return CreateEntriesResponse(
        message=f"Created/updated {len(created_entries)} entries",
        entries_created=len(created_entries),
        entries=entry_responses,
        errors=errors,
    )


@router.get("", response_model=EntryListResponse)
def get_entries(
    kpi_id: Optional[UUID] = Query(None, description="Filter by KPI ID"),
    start_date: Optional[date] = Query(None, description="Start date (inclusive)"),
    end_date: Optional[date] = Query(None, description="End date (inclusive)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum entries to return"),
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Query data entries with optional filters.
    """
    _, org = user_org

    entries = EntryService.get_entries(
        db=db,
        org_id=org.id,
        kpi_id=kpi_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    entry_responses = []
    for entry in entries:
        response = DataEntryResponse(
            id=entry.id,
            kpi_id=entry.kpi_id,
            kpi_name=entry.kpi_definition.name if entry.kpi_definition else None,
            date=entry.date,
            values=entry.values,
            calculated_value=entry.calculated_value,
            entered_by=entry.entered_by,
            created_at=entry.created_at,
        )
        entry_responses.append(response)

    return EntryListResponse(
        entries=entry_responses,
        total=len(entry_responses),
    )


@router.get("/today", response_model=TodayFormResponse)
def get_today_form(
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get today's entry form.
    Lists all KPIs with their required input fields and shows which ones already have data.
    """
    _, org = user_org
    today = date.today()

    form_items, completed_count, total_count = EntryService.get_today_form(
        db=db,
        org_id=org.id,
        today=today,
    )

    kpi_form_items = []
    for item in form_items:
        today_entry = None
        if item["today_entry"]:
            entry = item["today_entry"]
            today_entry = DataEntryResponse(
                id=entry.id,
                kpi_id=entry.kpi_id,
                kpi_name=item["kpi_name"],
                date=entry.date,
                values=entry.values,
                calculated_value=entry.calculated_value,
                entered_by=entry.entered_by,
                created_at=entry.created_at,
            )

        kpi_form_items.append(KPIFormItem(
            kpi_id=item["kpi_id"],
            kpi_name=item["kpi_name"],
            category=item["category"],
            formula=item["formula"],
            input_fields=item["input_fields"],
            has_entry_today=item["has_entry_today"],
            today_entry=today_entry,
        ))

    return TodayFormResponse(
        date=today,
        kpis=kpi_form_items,
        completed_count=completed_count,
        total_count=total_count,
    )


@router.get("/summary", response_model=StatsSummaryResponse)
def get_entry_summary(
    kpi_id: UUID = Query(..., description="KPI ID"),
    period: str = Query("30d", pattern="^(7d|30d|90d)$", description="Time period"),
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get statistical summary for a KPI over a period.
    Returns current value, mean, median, std_dev, min, max, and trend.
    """
    _, org = user_org

    result = EntryService.get_summary(
        db=db,
        org_id=org.id,
        kpi_id=kpi_id,
        period=period,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KPI not found",
        )

    kpi, stats = result

    return StatsSummaryResponse(
        kpi_id=kpi.id,
        kpi_name=kpi.name,
        period=period,
        current_value=stats.current_value,
        mean=stats.mean,
        median=stats.median,
        std_dev=stats.std_dev,
        min_value=stats.min_value,
        max_value=stats.max_value,
        trend=stats.trend,
        trend_percentage=stats.trend_percentage,
        data_points=stats.data_points,
    )


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: UUID,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Delete a data entry.
    """
    _, org = user_org

    entry = EntryService.get_entry_by_id(db, entry_id, org.id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        )

    EntryService.delete_entry(db, entry)
    return None


# --- New per-field entry endpoints ---

@router.post("/fields", response_model=CreateFieldEntriesResponse, status_code=status.HTTP_201_CREATED)
def create_field_entries(
    data: CreateFieldEntriesRequest,
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Submit per-field data entries for a date.
    Each data field value is entered once. Affected KPIs auto-recalculate.
    """
    user, org = user_org

    created_entries, kpis_recalculated, errors = EntryService.create_field_entries(
        db=db,
        org_id=org.id,
        user_id=user.id,
        entry_date=data.date,
        field_entries=data.entries,
    )

    entry_responses = []
    for entry in created_entries:
        response = FieldEntryResponse(
            id=entry.id,
            data_field_id=entry.data_field_id,
            data_field_name=entry.data_field.name if entry.data_field else None,
            room_name=entry.data_field.room.name if entry.data_field and entry.data_field.room else None,
            date=entry.date,
            value=entry.value,
            entered_by=entry.entered_by,
            created_at=entry.created_at,
        )
        entry_responses.append(response)

    return CreateFieldEntriesResponse(
        message=f"Created/updated {len(created_entries)} entries, {kpis_recalculated} KPIs recalculated",
        entries_created=len(created_entries),
        entries=entry_responses,
        kpis_recalculated=kpis_recalculated,
        errors=errors,
    )


@router.get("/fields/today", response_model=TodayFieldFormResponse)
def get_today_field_form(
    date_param: Optional[date] = Query(None, alias="date", description="Date (defaults to today)"),
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get per-field entry form grouped by room.
    Shows each unique data field once with today's value if entered.
    """
    user, org = user_org
    target_date = date_param or date.today()

    room_groups, completed_count, total_count = EntryService.get_today_field_form(
        db=db,
        org_id=org.id,
        user_role=user.role,
        user_id=user.id,
        today=target_date,
    )

    return TodayFieldFormResponse(
        date=target_date,
        rooms=[
            RoomFieldGroup(
                room_id=group["room_id"],
                room_name=group["room_name"],
                fields=[FieldFormItem(**f) for f in group["fields"]],
            )
            for group in room_groups
        ],
        completed_count=completed_count,
        total_count=total_count,
    )
