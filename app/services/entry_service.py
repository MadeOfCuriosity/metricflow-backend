"""
Service for handling data entry operations.
"""
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models import DataEntry, KPIDefinition
from app.schemas.entries import EntryValueInput
from app.services.calculation_service import CalculationService, StatsSummary


class EntryService:
    """Service for handling data entry business logic."""

    @staticmethod
    def create_entries(
        db: Session,
        org_id: UUID,
        user_id: UUID,
        entry_date: date,
        entries: list[EntryValueInput],
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

                # Check if entry already exists for this date
                existing = db.query(DataEntry).filter(
                    DataEntry.org_id == org_id,
                    DataEntry.kpi_id == entry_input.kpi_id,
                    DataEntry.date == entry_date
                ).first()

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
