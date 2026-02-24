"""
Service for handling data entry operations.
"""
import calendar
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models import DataEntry, KPIDefinition, DataField, DataFieldEntry, KPIDataField
from app.models.room import Room
from app.schemas.entries import EntryValueInput
from app.schemas.data_fields import FieldEntryInput
from app.services.calculation_service import CalculationService, StatsSummary


def normalize_date_for_interval(d: date, interval: str) -> date:
    """Snap a date to the canonical date for its interval period."""
    if interval == "weekly":
        # Snap to Monday of the week
        return d - timedelta(days=d.weekday())
    elif interval == "monthly":
        # Snap to the 1st of the month
        return d.replace(day=1)
    else:
        # daily and custom: use exact date
        return d


class EntryService:
    """Service for handling data entry business logic."""

    @staticmethod
    def create_entries(
        db: Session,
        org_id: UUID,
        user_id: UUID,
        entry_date: date,
        entries: list[EntryValueInput],
        room_id: Optional[UUID] = None,
    ) -> tuple[list[DataEntry], list[dict]]:
        """
        Create multiple data entries for a given date.

        Args:
            db: Database session
            org_id: Organization ID
            user_id: User creating the entries
            entry_date: Date for the entries
            entries: List of KPI entries with values

        Returns:
            Tuple of (created entries, errors)
        """
        created_entries = []
        errors = []

        for entry_input in entries:
            try:
                # Get the KPI definition
                kpi = db.query(KPIDefinition).filter(
                    KPIDefinition.id == entry_input.kpi_id,
                    KPIDefinition.org_id == org_id
                ).first()

                if not kpi:
                    errors.append({
                        "kpi_id": str(entry_input.kpi_id),
                        "error": "KPI not found"
                    })
                    continue

                # Validate that all required input fields are provided
                is_valid, missing = CalculationService.validate_input_values(
                    kpi.input_fields,
                    entry_input.values
                )
                if not is_valid:
                    errors.append({
                        "kpi_id": str(entry_input.kpi_id),
                        "error": f"Missing required fields: {', '.join(missing)}"
                    })
                    continue

                # Calculate the KPI value
                calc_result = CalculationService.calculate(kpi.formula, entry_input.values)
                if not calc_result.success:
                    errors.append({
                        "kpi_id": str(entry_input.kpi_id),
                        "error": calc_result.error
                    })
                    continue

                # Check if entry already exists for this date (and room)
                existing_query = db.query(DataEntry).filter(
                    DataEntry.org_id == org_id,
                    DataEntry.kpi_id == entry_input.kpi_id,
                    DataEntry.date == entry_date,
                )
                if room_id is not None:
                    existing_query = existing_query.filter(DataEntry.room_id == room_id)
                else:
                    existing_query = existing_query.filter(DataEntry.room_id.is_(None))
                existing = existing_query.first()

                if existing:
                    # Update existing entry
                    existing.values = entry_input.values
                    existing.calculated_value = calc_result.value
                    existing.entered_by = user_id
                    db.flush()
                    created_entries.append(existing)
                else:
                    # Create new entry
                    entry = DataEntry(
                        org_id=org_id,
                        kpi_id=entry_input.kpi_id,
                        room_id=room_id,
                        date=entry_date,
                        values=entry_input.values,
                        calculated_value=calc_result.value,
                        entered_by=user_id,
                    )
                    db.add(entry)
                    db.flush()
                    created_entries.append(entry)

            except Exception as e:
                errors.append({
                    "kpi_id": str(entry_input.kpi_id),
                    "error": str(e)
                })

        if created_entries:
            db.commit()
            for entry in created_entries:
                db.refresh(entry)

        return created_entries, errors

    @staticmethod
    def get_entries(
        db: Session,
        org_id: UUID,
        kpi_id: Optional[UUID] = None,
        room_id: Optional[UUID] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 100,
    ) -> list[DataEntry]:
        """
        Query data entries with optional filters.
        """
        query = db.query(DataEntry).filter(DataEntry.org_id == org_id)

        if kpi_id:
            query = query.filter(DataEntry.kpi_id == kpi_id)
        if room_id is not None:
            query = query.filter(DataEntry.room_id == room_id)
        if start_date:
            query = query.filter(DataEntry.date >= start_date)
        if end_date:
            query = query.filter(DataEntry.date <= end_date)

        return query.order_by(DataEntry.date.desc()).limit(limit).all()

    @staticmethod
    def get_today_form(
        db: Session,
        org_id: UUID,
        today: Optional[date] = None,
    ) -> tuple[list[dict], int, int]:
        """
        Get today's entry form data.

        Returns:
            Tuple of (kpi form items, completed count, total count)
        """
        if today is None:
            today = date.today()

        # Get all KPIs for the org
        kpis = db.query(KPIDefinition).filter(
            KPIDefinition.org_id == org_id
        ).order_by(KPIDefinition.category, KPIDefinition.name).all()

        # Get today's entries
        today_entries = db.query(DataEntry).filter(
            DataEntry.org_id == org_id,
            DataEntry.date == today
        ).all()

        # Create a lookup dict for quick access
        entries_by_kpi = {str(e.kpi_id): e for e in today_entries}

        form_items = []
        completed_count = 0

        for kpi in kpis:
            kpi_id_str = str(kpi.id)
            has_entry = kpi_id_str in entries_by_kpi
            entry = entries_by_kpi.get(kpi_id_str)

            if has_entry:
                completed_count += 1

            form_items.append({
                "kpi_id": kpi.id,
                "kpi_name": kpi.name,
                "category": kpi.category,
                "formula": kpi.formula,
                "input_fields": kpi.input_fields,
                "has_entry_today": has_entry,
                "today_entry": entry,
            })

        return form_items, completed_count, len(kpis)

    @staticmethod
    def get_summary(
        db: Session,
        org_id: UUID,
        kpi_id: UUID,
        period: str = "30d",
    ) -> Optional[tuple[KPIDefinition, StatsSummary]]:
        """
        Get statistical summary for a KPI over a period.

        Args:
            db: Database session
            org_id: Organization ID
            kpi_id: KPI ID
            period: Time period ("7d", "30d", "90d")

        Returns:
            Tuple of (KPI definition, stats summary) or None if KPI not found
        """
        # Get the KPI
        kpi = db.query(KPIDefinition).filter(
            KPIDefinition.id == kpi_id,
            KPIDefinition.org_id == org_id
        ).first()

        if not kpi:
            return None

        # Parse period
        period_days = {
            "7d": 7,
            "30d": 30,
            "90d": 90,
        }
        days = period_days.get(period, 30)

        # Calculate date range
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        # Get entries for the period
        entries = db.query(DataEntry).filter(
            DataEntry.org_id == org_id,
            DataEntry.kpi_id == kpi_id,
            DataEntry.date >= start_date,
            DataEntry.date <= end_date
        ).order_by(DataEntry.date.desc()).all()

        # Extract calculated values
        values = [e.calculated_value for e in entries]

        # Calculate stats
        stats = CalculationService.calculate_stats(values)

        return kpi, stats

    @staticmethod
    def get_entry_by_id(
        db: Session,
        entry_id: UUID,
        org_id: UUID,
    ) -> Optional[DataEntry]:
        """Get a single entry by ID."""
        return db.query(DataEntry).filter(
            DataEntry.id == entry_id,
            DataEntry.org_id == org_id
        ).first()

    @staticmethod
    def delete_entry(db: Session, entry: DataEntry) -> bool:
        """Delete a data entry."""
        db.delete(entry)
        db.commit()
        return True

    # --- New per-field entry methods ---

    @staticmethod
    def create_field_entries(
        db: Session,
        org_id: UUID,
        user_id: UUID,
        entry_date: date,
        field_entries: list[FieldEntryInput],
    ) -> tuple[list[DataFieldEntry], int, list[dict]]:
        """
        Create per-field data entries and auto-recalculate affected KPIs.

        Returns:
            Tuple of (created field entries, kpis recalculated count, errors)
        """
        created_entries = []
        errors = []
        affected_field_ids = set()

        for entry_input in field_entries:
            try:
                # Verify the data field exists and belongs to this org
                field = db.query(DataField).filter(
                    DataField.id == entry_input.data_field_id,
                    DataField.org_id == org_id,
                ).first()

                if not field:
                    errors.append({
                        "data_field_id": str(entry_input.data_field_id),
                        "error": "Data field not found",
                    })
                    continue

                # Upsert: check if entry already exists
                existing = db.query(DataFieldEntry).filter(
                    DataFieldEntry.org_id == org_id,
                    DataFieldEntry.data_field_id == entry_input.data_field_id,
                    DataFieldEntry.date == entry_date,
                ).first()

                if existing:
                    existing.value = entry_input.value
                    existing.entered_by = user_id
                    db.flush()
                    created_entries.append(existing)
                else:
                    entry = DataFieldEntry(
                        org_id=org_id,
                        data_field_id=entry_input.data_field_id,
                        date=entry_date,
                        value=entry_input.value,
                        entered_by=user_id,
                    )
                    db.add(entry)
                    db.flush()
                    created_entries.append(entry)

                affected_field_ids.add(entry_input.data_field_id)

            except Exception as e:
                errors.append({
                    "data_field_id": str(entry_input.data_field_id),
                    "error": str(e),
                })

        # Auto-recalculate affected KPIs
        kpis_recalculated = 0
        if affected_field_ids:
            kpis_recalculated = EntryService._recalculate_kpis(
                db, org_id, user_id, entry_date, affected_field_ids
            )

        if created_entries:
            db.commit()
            for entry in created_entries:
                db.refresh(entry)

        return created_entries, kpis_recalculated, errors

    @staticmethod
    def _recalculate_kpis(
        db: Session,
        org_id: UUID,
        user_id: UUID,
        entry_date: date,
        affected_field_ids: set[UUID],
    ) -> int:
        """
        Recalculate all KPIs that depend on the given data fields for the given date.
        Groups fields by room_id so each room gets its own DataEntry.
        Returns the number of KPIs recalculated.
        """
        # Find all KPIs that reference any of the affected data fields
        kpi_links = db.query(KPIDataField).filter(
            KPIDataField.data_field_id.in_(affected_field_ids)
        ).all()

        # Group by KPI ID
        kpi_ids = set(link.kpi_id for link in kpi_links)
        recalculated = 0

        for kpi_id in kpi_ids:
            kpi = db.query(KPIDefinition).filter(
                KPIDefinition.id == kpi_id,
                KPIDefinition.org_id == org_id,
            ).first()

            if not kpi:
                continue

            # Get all data field links for this KPI
            kpi_field_links = db.query(KPIDataField).filter(
                KPIDataField.kpi_id == kpi_id
            ).all()

            # Group field links by room_id (from their DataField)
            fields_by_room: dict[Optional[UUID], list] = {}
            for link in kpi_field_links:
                field = db.query(DataField).filter(DataField.id == link.data_field_id).first()
                room_id = field.room_id if field else None
                if room_id not in fields_by_room:
                    fields_by_room[room_id] = []
                fields_by_room[room_id].append(link)

            # Recalculate per room group
            for room_id, room_links in fields_by_room.items():
                values = {}
                all_present = True
                for link in room_links:
                    field_entry = db.query(DataFieldEntry).filter(
                        DataFieldEntry.org_id == org_id,
                        DataFieldEntry.data_field_id == link.data_field_id,
                        DataFieldEntry.date == entry_date,
                    ).first()

                    if field_entry:
                        values[link.variable_name] = field_entry.value
                    else:
                        all_present = False
                        break

                if not all_present:
                    continue

                # Calculate KPI value
                calc_result = CalculationService.calculate(kpi.formula, values)
                if not calc_result.success:
                    continue

                # Upsert into data_entries with room_id
                existing_query = db.query(DataEntry).filter(
                    DataEntry.org_id == org_id,
                    DataEntry.kpi_id == kpi_id,
                    DataEntry.date == entry_date,
                )
                if room_id is not None:
                    existing_query = existing_query.filter(DataEntry.room_id == room_id)
                else:
                    existing_query = existing_query.filter(DataEntry.room_id.is_(None))
                existing_kpi_entry = existing_query.first()

                if existing_kpi_entry:
                    existing_kpi_entry.values = values
                    existing_kpi_entry.calculated_value = calc_result.value
                    existing_kpi_entry.entered_by = user_id
                else:
                    kpi_entry = DataEntry(
                        org_id=org_id,
                        kpi_id=kpi_id,
                        room_id=room_id,
                        date=entry_date,
                        values=values,
                        calculated_value=calc_result.value,
                        entered_by=user_id,
                    )
                    db.add(kpi_entry)

                db.flush()
                recalculated += 1

        return recalculated

    @staticmethod
    def get_today_field_form(
        db: Session,
        org_id: UUID,
        user_role: str,
        user_id: UUID,
        today: Optional[date] = None,
        interval: Optional[str] = None,
    ) -> tuple[list[dict], int, int]:
        """
        Get per-field entry form grouped by room.

        Args:
            interval: Optional filter by entry_interval ("daily", "weekly", "monthly", "custom").
                      When set, also normalizes the date for the interval.

        Returns:
            Tuple of (room groups, completed count, total count)
        """
        from app.services.data_field_service import DataFieldService

        if today is None:
            today = date.today()

        # Normalize the date for the requested interval
        if interval:
            today = normalize_date_for_interval(today, interval)

        # Get accessible data fields
        fields = DataFieldService.get_accessible_data_fields(
            db, org_id, user_role, user_id
        )

        # Filter by interval if specified
        if interval:
            fields = [f for f in fields if f.entry_interval == interval]

        # Get field entries for the target date
        field_ids = [f.id for f in fields]
        today_entries = db.query(DataFieldEntry).filter(
            DataFieldEntry.org_id == org_id,
            DataFieldEntry.data_field_id.in_(field_ids),
            DataFieldEntry.date == today,
        ).all() if field_ids else []

        entries_by_field = {str(e.data_field_id): e for e in today_entries}

        # Group fields by room
        room_groups: dict[str, dict] = {}
        completed_count = 0
        total_count = len(fields)

        for field in fields:
            room_key = str(field.room_id) if field.room_id else "unassigned"
            if room_key not in room_groups:
                room_name = field.room.name if field.room else "Unassigned"
                room_groups[room_key] = {
                    "room_id": field.room_id,
                    "room_name": room_name,
                    "fields": [],
                }

            field_id_str = str(field.id)
            has_entry = field_id_str in entries_by_field
            entry = entries_by_field.get(field_id_str)

            if has_entry:
                completed_count += 1

            room_groups[room_key]["fields"].append({
                "data_field_id": field.id,
                "data_field_name": field.name,
                "variable_name": field.variable_name,
                "unit": field.unit,
                "entry_interval": field.entry_interval,
                "has_entry_today": has_entry,
                "today_value": entry.value if entry else None,
            })

        return list(room_groups.values()), completed_count, total_count

    @staticmethod
    def get_sheet_data(
        db: Session,
        org_id: UUID,
        user_role: str,
        user_id: UUID,
        year: int,
        month: int,
        room_id: Optional[UUID] = None,
    ) -> dict:
        """
        Get spreadsheet-style data for a month.
        Returns all daily-interval fields with their entries across the month.
        """
        from app.services.data_field_service import DataFieldService

        # Build date range for the month (up to today if current month)
        days_in_month = calendar.monthrange(year, month)[1]
        month_start = date(year, month, 1)
        month_end = date(year, month, days_in_month)
        today = date.today()
        effective_end = min(month_end, today)

        dates = []
        d = month_start
        while d <= effective_end:
            dates.append(d)
            d += timedelta(days=1)

        date_strings = [d.isoformat() for d in dates]

        # Get accessible data fields (daily interval only)
        fields = DataFieldService.get_accessible_data_fields(
            db, org_id, user_role, user_id
        )
        fields = [f for f in fields if f.entry_interval == "daily"]

        if room_id:
            fields = [f for f in fields if f.room_id == room_id]

        if not fields:
            return {
                "month": f"{year:04d}-{month:02d}",
                "dates": date_strings,
                "room_groups": [],
                "total_filled": 0,
                "total_cells": 0,
            }

        field_ids = [f.id for f in fields]

        # Batch-fetch all entries for these fields in the date range
        entries = db.query(DataFieldEntry).filter(
            DataFieldEntry.org_id == org_id,
            DataFieldEntry.data_field_id.in_(field_ids),
            DataFieldEntry.date >= month_start,
            DataFieldEntry.date <= effective_end,
        ).all()

        # Build lookup: (field_id, date_str) -> value
        entry_map: dict[tuple, float] = {}
        for e in entries:
            entry_map[(e.data_field_id, e.date.isoformat())] = e.value

        # Group fields by room
        room_groups_dict: dict[str, dict] = {}
        total_filled = 0
        total_cells = 0

        for field in fields:
            room_key = str(field.room_id) if field.room_id else "unassigned"
            if room_key not in room_groups_dict:
                room_groups_dict[room_key] = {
                    "room_id": field.room_id,
                    "room_name": field.room.name if field.room else "Unassigned",
                    "fields": [],
                }

            values: dict[str, Optional[float]] = {}
            mtd = 0.0
            for ds in date_strings:
                val = entry_map.get((field.id, ds))
                values[ds] = val
                if val is not None:
                    mtd += val
                    total_filled += 1
                total_cells += 1

            room_groups_dict[room_key]["fields"].append({
                "data_field_id": field.id,
                "name": field.name,
                "variable_name": field.variable_name,
                "unit": field.unit,
                "entry_interval": field.entry_interval,
                "values": values,
                "mtd": mtd,
            })

        return {
            "month": f"{year:04d}-{month:02d}",
            "dates": date_strings,
            "room_groups": list(room_groups_dict.values()),
            "total_filled": total_filled,
            "total_cells": total_cells,
        }
