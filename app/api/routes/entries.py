import csv
import io
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user_org
from app.models import User, Organization, DataField
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
    CSVImportResponse,
    FieldEntryInput,
    FieldEntryResponse,
    RoomFieldGroup,
    FieldFormItem,
    TodayFieldFormResponse,
    SheetFieldRow,
    SheetRoomGroup,
    SheetViewResponse,
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
        room_id=data.room_id,
    )

    # Get KPI names for response
    entry_responses = []
    for entry in created_entries:
        response = DataEntryResponse(
            id=entry.id,
            kpi_id=entry.kpi_id,
            kpi_name=entry.kpi_definition.name if entry.kpi_definition else None,
            room_id=entry.room_id,
            room_name=entry.room.name if entry.room else None,
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
    room_id: Optional[UUID] = Query(None, description="Filter by Room ID"),
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
        room_id=room_id,
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
            room_id=entry.room_id,
            room_name=entry.room.name if entry.room else None,
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
    interval: Optional[str] = Query(None, description="Filter by entry interval: daily, weekly, monthly, custom"),
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get per-field entry form grouped by room.
    Shows each unique data field once with the value if entered for the given date.
    Optionally filter by entry_interval; date is normalized for the interval.
    """
    if interval and interval not in ("daily", "weekly", "monthly", "custom"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid interval. Must be one of: daily, weekly, monthly, custom",
        )

    user, org = user_org
    target_date = date_param or date.today()

    room_groups, completed_count, total_count = EntryService.get_today_field_form(
        db=db,
        org_id=org.id,
        user_role=user.role,
        user_id=user.id,
        today=target_date,
        interval=interval,
    )

    # The service normalizes the date; extract the actual date used
    from app.services.entry_service import normalize_date_for_interval
    effective_date = normalize_date_for_interval(target_date, interval) if interval else target_date

    return TodayFieldFormResponse(
        date=effective_date,
        interval=interval,
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


@router.get("/fields/sheet", response_model=SheetViewResponse)
def get_sheet_view(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$", description="Month in YYYY-MM format"),
    room_id: Optional[UUID] = Query(None, description="Filter by room ID"),
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Get spreadsheet-style data for a month.
    Returns all daily-interval fields grouped by room with values for each day.
    """
    user, org = user_org

    try:
        year, month_num = int(month[:4]), int(month[5:7])
        if not 1 <= month_num <= 12:
            raise ValueError
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid month format. Use YYYY-MM (e.g., 2026-02)",
        )

    data = EntryService.get_sheet_data(
        db=db,
        org_id=org.id,
        user_role=user.role,
        user_id=user.id,
        year=year,
        month=month_num,
        room_id=room_id,
    )

    return SheetViewResponse(
        month=data["month"],
        dates=data["dates"],
        room_groups=[
            SheetRoomGroup(
                room_id=group["room_id"],
                room_name=group["room_name"],
                fields=[SheetFieldRow(**f) for f in group["fields"]],
            )
            for group in data["room_groups"]
        ],
        total_filled=data["total_filled"],
        total_cells=data["total_cells"],
    )


@router.post("/fields/import-csv", response_model=CSVImportResponse)
async def import_csv_field_entries(
    file: UploadFile = File(...),
    user_org: tuple[User, Organization] = Depends(get_current_user_org),
    db: Session = Depends(get_db),
):
    """
    Import data field entries from a CSV file.
    CSV format: first column is 'field' (data field name or variable_name),
    remaining columns are dates (YYYY-MM-DD). Each row is one data field
    with values across dates horizontally.

    Example:
        field,2026-01-15,2026-01-16,2026-01-17
        revenue,15000,18500,20000
        deals_closed,5,7,3
    """
    user, org = user_org

    # Validate file type
    if file.content_type and file.content_type not in (
        "text/csv",
        "application/vnd.ms-excel",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV",
        )

    # Read and decode file
    try:
        contents = await file.read()
        text = contents.decode("utf-8-sig")  # Handle BOM
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be UTF-8 encoded",
        )

    # Parse CSV
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]

    if len(rows) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must have a header row and at least one data row",
        )

    # Parse header: first cell should be "field", rest are dates
    header = [h.strip() for h in rows[0]]

    if not header or header[0].lower() not in ("field", "field_name", "name", "data_field"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="First column header must be 'field'. Format: field,2026-01-15,2026-01-16,...",
        )

    # Parse date columns
    date_columns: list[tuple[int, date]] = []
    invalid_date_headers: list[str] = []

    for col_idx, header_val in enumerate(header[1:], start=1):
        if not header_val:
            continue
        try:
            parsed_date = date.fromisoformat(header_val)
            date_columns.append((col_idx, parsed_date))
        except ValueError:
            invalid_date_headers.append(header_val)

    if not date_columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No valid date columns found. Column headers after 'field' must be dates (YYYY-MM-DD). Got: {header[1:]}",
        )

    # Build field lookup maps
    org_fields = db.query(DataField).filter(DataField.org_id == org.id).all()
    var_map = {f.variable_name: f for f in org_fields}
    name_map = {f.name.lower(): f for f in org_fields}

    # Process data rows (each row = one data field)
    rows_processed = 0
    total_entries_created = 0
    total_kpis_recalculated = 0
    unmatched_rows: list[str] = []
    errors: list[dict] = []

    # Collect entries grouped by date for batch processing
    date_entries: dict[date, list[FieldEntryInput]] = {}

    for row_num, row in enumerate(rows[1:], start=2):
        if not row or not row[0].strip():
            errors.append({"row": row_num, "error": "Empty field name"})
            continue

        field_name = row[0].strip()
        rows_processed += 1

        # Match field name to a DataField
        field_obj = var_map.get(field_name) or name_map.get(field_name.lower())
        if not field_obj:
            unmatched_rows.append(field_name)
            continue

        # Read values for each date column
        for col_idx, entry_date in date_columns:
            if col_idx >= len(row):
                continue
            raw_value = row[col_idx].strip()
            if not raw_value:
                continue
            try:
                value = float(raw_value.replace(",", ""))
            except ValueError:
                errors.append({"row": row_num, "error": f"Invalid number '{raw_value}' for date {entry_date.isoformat()}"})
                continue

            if entry_date not in date_entries:
                date_entries[entry_date] = []
            date_entries[entry_date].append(FieldEntryInput(data_field_id=field_obj.id, value=value))

    # Submit entries grouped by date
    for entry_date in sorted(date_entries.keys()):
        field_entries = date_entries[entry_date]
        created, kpis_recalc, batch_errors = EntryService.create_field_entries(
            db=db,
            org_id=org.id,
            user_id=user.id,
            entry_date=entry_date,
            field_entries=field_entries,
        )
        total_entries_created += len(created)
        total_kpis_recalculated += kpis_recalc
        for err in batch_errors:
            errors.append({"row": 0, "error": f"{entry_date.isoformat()}: {err.get('error', 'Unknown error')}"})

    return CSVImportResponse(
        rows_processed=rows_processed,
        entries_created=total_entries_created,
        kpis_recalculated=total_kpis_recalculated,
        errors=errors,
        unmatched_columns=unmatched_rows + invalid_date_headers,
    )
