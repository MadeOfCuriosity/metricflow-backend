from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.formula_parser import extract_input_fields, validate_formula
from app.models import KPIDefinition, DataEntry, KPIDataField
from app.models.kpi_definition import TimePeriod
from app.schemas.kpi import KPICreateRequest, KPIUpdateRequest
from app.services.data_field_service import DataFieldService


# Default KPI presets
DEFAULT_PRESETS = [
    {
        "name": "Conversion Rate",
        "description": "Percentage of leads that convert to closed deals",
        "formula": "(deals_closed / leads_received) * 100",
        "category": "Sales",
        "time_period": "daily",
    },
    {
        "name": "Customer Acquisition Cost (CAC)",
        "description": "Average cost to acquire a new customer",
        "formula": "marketing_spend / new_customers",
        "category": "Marketing",
        "time_period": "monthly",
    },
    {
        "name": "Revenue per Employee",
        "description": "Total revenue divided by number of employees",
        "formula": "total_revenue / employee_count",
        "category": "Operations",
        "time_period": "monthly",
    },
    {
        "name": "Average Deal Size",
        "description": "Average revenue per closed deal",
        "formula": "total_revenue / deals_closed",
        "category": "Sales",
        "time_period": "weekly",
    },
    {
        "name": "Lead Response Time",
        "description": "Average time to respond to leads (in hours)",
        "formula": "total_response_time / leads_contacted",
        "category": "Sales",
        "time_period": "daily",
    },
]


class KPIService:
    """Service for handling KPI business logic."""

    @staticmethod
    def get_all_kpis(db: Session, org_id: UUID) -> list[KPIDefinition]:
        """Get all KPIs for an organization (both presets and custom)."""
        return db.query(KPIDefinition).filter(
            KPIDefinition.org_id == org_id
        ).order_by(KPIDefinition.category, KPIDefinition.name).all()

    @staticmethod
    def get_kpi_by_id(
        db: Session,
        kpi_id: UUID,
        org_id: UUID
    ) -> Optional[KPIDefinition]:
        """Get a single KPI by ID, ensuring it belongs to the org."""
        return db.query(KPIDefinition).filter(
            KPIDefinition.id == kpi_id,
            KPIDefinition.org_id == org_id
        ).first()

    @staticmethod
    def get_kpi_with_data(
        db: Session,
        kpi_id: UUID,
        org_id: UUID,
        limit: int = 30
    ) -> Optional[tuple[KPIDefinition, list[DataEntry]]]:
        """Get a KPI with its recent data entries."""
        kpi = KPIService.get_kpi_by_id(db, kpi_id, org_id)
        if not kpi:
            return None

        entries = db.query(DataEntry).filter(
            DataEntry.kpi_id == kpi_id,
            DataEntry.org_id == org_id
        ).order_by(DataEntry.date.desc()).limit(limit).all()

        return kpi, entries

    @staticmethod
    def create_kpi(
        db: Session,
        org_id: UUID,
        user_id: UUID,
        data: KPICreateRequest,
    ) -> KPIDefinition:
        """Create a new custom KPI with DataField integration."""
        # Extract input fields from formula
        input_fields = extract_input_fields(data.formula)

        # Convert time_period to model enum
        time_period_str = data.time_period.value if hasattr(data.time_period, 'value') else str(data.time_period)
        time_period_value = TimePeriod(time_period_str)

        kpi = KPIDefinition(
            org_id=org_id,
            name=data.name,
            description=data.description,
            formula=data.formula,
            input_fields=input_fields,
            category=data.category,
            time_period=time_period_value,
            is_preset=False,
            is_shared=data.is_shared,
            created_by=user_id,
        )
        db.add(kpi)
        db.flush()  # Get the KPI ID without committing

        # Resolve formula variables to DataFields (auto-create if needed)
        variable_to_field = DataFieldService.auto_create_from_formula(
            db=db,
            org_id=org_id,
            user_id=user_id,
            formula=data.formula,
            room_id=getattr(data, 'room_id', None),
            data_field_mappings=getattr(data, 'data_field_mappings', None),
        )

        # Create KPI -> DataField links
        DataFieldService.create_kpi_data_field_links(db, kpi.id, variable_to_field)

        db.commit()
        db.refresh(kpi)
        return kpi

    @staticmethod
    def update_kpi(
        db: Session,
        kpi: KPIDefinition,
        data: KPIUpdateRequest,
    ) -> KPIDefinition:
        """Update an existing KPI (custom only, not presets)."""
        if kpi.is_preset:
            raise ValueError("Cannot modify preset KPIs")

        formula_changed = False

        # Update fields if provided
        if data.name is not None:
            kpi.name = data.name
        if data.description is not None:
            kpi.description = data.description
        if data.formula is not None:
            kpi.formula = data.formula
            kpi.input_fields = extract_input_fields(data.formula)
            formula_changed = True
        if data.category is not None:
            kpi.category = data.category
        if data.time_period is not None:
            time_period_str = data.time_period.value if hasattr(data.time_period, 'value') else str(data.time_period)
            kpi.time_period = TimePeriod(time_period_str)
        if data.is_shared is not None:
            kpi.is_shared = data.is_shared

        # If formula changed, update DataField links
        if formula_changed:
            variable_to_field = DataFieldService.auto_create_from_formula(
                db=db,
                org_id=kpi.org_id,
                user_id=kpi.created_by,
                formula=kpi.formula,
            )
            DataFieldService.update_kpi_data_field_links(db, kpi.id, variable_to_field)

        db.commit()
        db.refresh(kpi)
        return kpi

    @staticmethod
    def delete_kpi(db: Session, kpi: KPIDefinition) -> bool:
        """
        Delete a KPI (soft delete by removing, but keeping data entries).
        Returns True if deleted, False if it's a preset.
        """
        if kpi.is_preset:
            raise ValueError("Cannot delete preset KPIs")

        # Note: DataEntry has ondelete='CASCADE', so entries will be removed
        # If you want to keep historical data, you could:
        # 1. Add an 'is_archived' field to KPIDefinition
        # 2. Set kpi.is_archived = True instead of deleting
        # For now, we'll do a hard delete as requested

        db.delete(kpi)
        db.commit()
        return True

    @staticmethod
    def get_available_presets(db: Session, org_id: UUID) -> list[dict]:
        """
        Get list of available preset KPIs that haven't been added yet.
        """
        # Get existing preset names for this org
        existing_names = set(
            name for (name,) in db.query(KPIDefinition.name).filter(
                KPIDefinition.org_id == org_id,
                KPIDefinition.is_preset == True
            ).all()
        )

        available = []
        for preset_data in DEFAULT_PRESETS:
            if preset_data["name"] not in existing_names:
                available.append(preset_data)

        return available

    @staticmethod
    def seed_presets(
        db: Session,
        org_id: UUID,
        preset_names: Optional[list[str]] = None
    ) -> list[KPIDefinition]:
        """
        Seed KPI presets for an organization.
        If preset_names is provided, only those specific presets are added.
        Skips presets that already exist (by name).
        """
        created_presets = []

        # Get existing preset names for this org
        existing_names = set(
            name for (name,) in db.query(KPIDefinition.name).filter(
                KPIDefinition.org_id == org_id,
                KPIDefinition.is_preset == True
            ).all()
        )

        for preset_data in DEFAULT_PRESETS:
            # Skip if preset already exists
            if preset_data["name"] in existing_names:
                continue

            # If specific presets requested, skip others
            if preset_names is not None and preset_data["name"] not in preset_names:
                continue

            # Validate formula and extract input fields
            is_valid, error, input_fields = validate_formula(preset_data["formula"])
            if not is_valid:
                # Skip invalid formulas (shouldn't happen with our defaults)
                continue

            # Get time_period, default to daily
            time_period_str = preset_data.get("time_period", "daily")
            time_period = TimePeriod(time_period_str)

            preset = KPIDefinition(
                org_id=org_id,
                name=preset_data["name"],
                description=preset_data["description"],
                formula=preset_data["formula"],
                input_fields=input_fields,
                category=preset_data["category"],
                time_period=time_period,
                is_preset=True,
                created_by=None,  # System preset
            )
            db.add(preset)
            db.flush()

            # Create DataField links for preset KPIs
            variable_to_field = DataFieldService.auto_create_from_formula(
                db=db,
                org_id=org_id,
                user_id=None,
                formula=preset_data["formula"],
            )
            DataFieldService.create_kpi_data_field_links(db, preset.id, variable_to_field)

            created_presets.append(preset)

        if created_presets:
            db.commit()
            for preset in created_presets:
                db.refresh(preset)

        return created_presets

    @staticmethod
    def check_kpi_name_exists(
        db: Session,
        org_id: UUID,
        name: str,
        exclude_id: Optional[UUID] = None
    ) -> bool:
        """Check if a KPI with the given name already exists in the org."""
        query = db.query(KPIDefinition).filter(
            KPIDefinition.org_id == org_id,
            KPIDefinition.name == name
        )
        if exclude_id:
            query = query.filter(KPIDefinition.id != exclude_id)
        return query.first() is not None
