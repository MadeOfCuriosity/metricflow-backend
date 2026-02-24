"""
Service for handling DataField operations.
"""
import re
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, exists

from app.models import DataField, DataFieldEntry, DataFieldRoom, KPIDataField, Room, UserRoomAssignment
from app.models.data_field import DataField as DataFieldModel
from app.schemas.data_fields import DataFieldCreateRequest, DataFieldUpdateRequest
from app.core.formula_parser import extract_input_fields


class DataFieldService:
    """Service for handling DataField business logic."""

    @staticmethod
    def generate_variable_name(name: str) -> str:
        """
        Convert a display name to a snake_case variable name.
        e.g., "Revenue Per Employee" -> "revenue_per_employee"
        """
        # Remove non-alphanumeric chars except spaces
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', name)
        # Replace spaces with underscores and convert to lowercase
        var_name = re.sub(r'\s+', '_', cleaned.strip()).lower()
        # Ensure it starts with a letter or underscore
        if var_name and var_name[0].isdigit():
            var_name = '_' + var_name
        return var_name or 'unnamed_field'

    @staticmethod
    def ensure_unique_variable_name(db: Session, org_id: UUID, base_name: str, exclude_id: Optional[UUID] = None) -> str:
        """
        Ensure variable_name is unique within the org.
        Appends _2, _3, etc. if needed.
        """
        var_name = DataFieldService.generate_variable_name(base_name)
        candidate = var_name
        counter = 2

        while True:
            query = db.query(DataField).filter(
                DataField.org_id == org_id,
                DataField.variable_name == candidate,
            )
            if exclude_id:
                query = query.filter(DataField.id != exclude_id)
            if not query.first():
                return candidate
            candidate = f"{var_name}_{counter}"
            counter += 1

    @staticmethod
    def get_all_data_fields(
        db: Session,
        org_id: UUID,
        room_id: Optional[UUID] = None,
    ) -> list[DataField]:
        """Get all data fields for an org, optionally filtered by room."""
        query = db.query(DataField).filter(DataField.org_id == org_id)
        if room_id:
            query = query.filter(
                exists().where(
                    and_(
                        DataFieldRoom.data_field_id == DataField.id,
                        DataFieldRoom.room_id == room_id,
                    )
                )
            )
        return query.order_by(DataField.name).all()

    @staticmethod
    def get_accessible_data_fields(
        db: Session,
        org_id: UUID,
        user_role: str,
        user_id: UUID,
    ) -> list[DataField]:
        """
        Get data fields accessible to the user.
        Admin: all fields in org.
        Room admin: fields in assigned rooms + sub-rooms + unassigned fields.
        """
        query = db.query(DataField).filter(DataField.org_id == org_id)

        if user_role != "admin":
            # Get accessible room IDs for room_admin
            assignments = db.query(UserRoomAssignment.room_id).filter(
                UserRoomAssignment.user_id == user_id
            ).all()
            assigned_ids = [a.room_id for a in assignments]

            # Recursively include all descendant sub-rooms (not just one level)
            all_room_ids = list(assigned_ids)
            parent_ids = assigned_ids
            while parent_ids:
                sub_rooms = db.query(Room.id).filter(
                    Room.parent_room_id.in_(parent_ids)
                ).all()
                child_ids = [s.id for s in sub_rooms]
                if not child_ids:
                    break
                all_room_ids.extend(child_ids)
                parent_ids = child_ids

            # Filter to fields in accessible rooms OR fields with no room assignments
            from sqlalchemy import or_
            has_room_in_list = exists().where(
                and_(
                    DataFieldRoom.data_field_id == DataField.id,
                    DataFieldRoom.room_id.in_(all_room_ids),
                )
            )
            has_no_rooms = ~exists().where(
                DataFieldRoom.data_field_id == DataField.id
            )
            query = query.filter(or_(has_room_in_list, has_no_rooms))

        return query.order_by(DataField.name).all()

    @staticmethod
    def get_data_field_by_id(
        db: Session,
        field_id: UUID,
        org_id: UUID,
    ) -> Optional[DataField]:
        """Get a single data field by ID."""
        return db.query(DataField).filter(
            DataField.id == field_id,
            DataField.org_id == org_id,
        ).first()

    @staticmethod
    def get_data_field_by_variable(
        db: Session,
        org_id: UUID,
        variable_name: str,
    ) -> Optional[DataField]:
        """Get a data field by its variable_name within an org."""
        return db.query(DataField).filter(
            DataField.org_id == org_id,
            DataField.variable_name == variable_name,
        ).first()

    @staticmethod
    def _sync_room_assignments(db: Session, field: DataField, room_ids: list[UUID]) -> None:
        """Replace a field's room assignments with the given room_ids."""
        # Remove existing assignments
        db.query(DataFieldRoom).filter(DataFieldRoom.data_field_id == field.id).delete()
        # Create new assignments
        for rid in room_ids:
            db.add(DataFieldRoom(data_field_id=field.id, room_id=rid))

    @staticmethod
    def create_data_field(
        db: Session,
        org_id: UUID,
        user_id: UUID,
        data: DataFieldCreateRequest,
    ) -> DataField:
        """Create a new data field."""
        variable_name = DataFieldService.ensure_unique_variable_name(db, org_id, data.name)

        field = DataField(
            org_id=org_id,
            name=data.name,
            variable_name=variable_name,
            description=data.description,
            unit=data.unit,
            entry_interval=data.entry_interval,
            created_by=user_id,
        )
        db.add(field)
        db.flush()

        # Create room assignments
        if data.room_ids:
            DataFieldService._sync_room_assignments(db, field, data.room_ids)

        db.commit()
        db.refresh(field)
        return field

    @staticmethod
    def update_data_field(
        db: Session,
        field: DataField,
        data: DataFieldUpdateRequest,
    ) -> DataField:
        """Update a data field. variable_name is immutable."""
        if data.name is not None:
            field.name = data.name
        if data.description is not None:
            field.description = data.description
        if data.unit is not None:
            field.unit = data.unit
        if data.entry_interval is not None:
            field.entry_interval = data.entry_interval
        if data.room_ids is not None:
            DataFieldService._sync_room_assignments(db, field, data.room_ids)

        db.commit()
        db.refresh(field)
        return field

    @staticmethod
    def delete_data_field(db: Session, field: DataField) -> bool:
        """
        Delete a data field. Only allowed if no KPIs reference it.
        Returns True if deleted, raises ValueError if in use.
        """
        kpi_count = db.query(KPIDataField).filter(
            KPIDataField.data_field_id == field.id
        ).count()

        if kpi_count > 0:
            raise ValueError(
                f"Cannot delete data field '{field.name}': used by {kpi_count} KPI(s)"
            )

        db.delete(field)
        db.commit()
        return True

    @staticmethod
    def get_kpi_count(db: Session, field_id: UUID) -> int:
        """Get the number of KPIs that reference this data field."""
        return db.query(KPIDataField).filter(
            KPIDataField.data_field_id == field_id
        ).count()

    @staticmethod
    def get_latest_entry(db: Session, field_id: UUID) -> Optional[DataFieldEntry]:
        """Get the most recent entry for a data field."""
        return db.query(DataFieldEntry).filter(
            DataFieldEntry.data_field_id == field_id
        ).order_by(DataFieldEntry.date.desc()).first()

    @staticmethod
    def auto_create_from_formula(
        db: Session,
        org_id: UUID,
        user_id: UUID,
        formula: str,
        room_ids: Optional[list[UUID]] = None,
        data_field_mappings: Optional[dict[str, UUID]] = None,
    ) -> dict[str, UUID]:
        """
        Parse formula, create DataFields for any new variables, return variable->field_id mapping.
        If data_field_mappings is provided, use explicit mappings and only create missing ones.
        """
        variables = extract_input_fields(formula)
        result_mapping: dict[str, UUID] = {}

        for var_name in variables:
            # Check explicit mapping first
            if data_field_mappings and var_name in data_field_mappings:
                result_mapping[var_name] = data_field_mappings[var_name]
                continue

            # Check if variable already exists in org
            existing = DataFieldService.get_data_field_by_variable(db, org_id, var_name)
            if existing:
                result_mapping[var_name] = existing.id
                continue

            # Create new data field
            display_name = var_name.replace('_', ' ').title()
            field = DataField(
                org_id=org_id,
                name=display_name,
                variable_name=var_name,
                created_by=user_id,
            )
            db.add(field)
            db.flush()

            # Assign rooms if provided
            if room_ids:
                for rid in room_ids:
                    db.add(DataFieldRoom(data_field_id=field.id, room_id=rid))

            result_mapping[var_name] = field.id

        return result_mapping

    @staticmethod
    def create_kpi_data_field_links(
        db: Session,
        kpi_id: UUID,
        variable_to_field: dict[str, UUID],
    ) -> None:
        """Create KPIDataField join records for a KPI."""
        for var_name, field_id in variable_to_field.items():
            link = KPIDataField(
                kpi_id=kpi_id,
                data_field_id=field_id,
                variable_name=var_name,
            )
            db.add(link)

    @staticmethod
    def update_kpi_data_field_links(
        db: Session,
        kpi_id: UUID,
        variable_to_field: dict[str, UUID],
    ) -> None:
        """Replace KPIDataField links for a KPI (used when formula changes)."""
        # Remove existing links
        db.query(KPIDataField).filter(KPIDataField.kpi_id == kpi_id).delete()
        # Create new links
        DataFieldService.create_kpi_data_field_links(db, kpi_id, variable_to_field)

    @staticmethod
    def enrich_with_metadata(
        db: Session,
        fields: list[DataField],
    ) -> list[dict]:
        """
        Enrich data fields with room info, kpi_count, and latest_value.
        Returns list of dicts ready for DataFieldResponse.
        Uses batch queries to avoid N+1 problems.
        """
        from app.services.room_service import RoomService

        if not fields:
            return []

        field_ids = [f.id for f in fields]

        # Batch: get KPI counts for all fields in one query
        kpi_counts_query = (
            db.query(KPIDataField.data_field_id, func.count(KPIDataField.id))
            .filter(KPIDataField.data_field_id.in_(field_ids))
            .group_by(KPIDataField.data_field_id)
            .all()
        )
        kpi_count_map = dict(kpi_counts_query)

        # Batch: get latest entries for all fields in one query using a subquery
        latest_subq = (
            db.query(
                DataFieldEntry.data_field_id,
                func.max(DataFieldEntry.date).label("max_date"),
            )
            .filter(DataFieldEntry.data_field_id.in_(field_ids))
            .group_by(DataFieldEntry.data_field_id)
            .subquery()
        )
        latest_entries = (
            db.query(DataFieldEntry)
            .join(
                latest_subq,
                and_(
                    DataFieldEntry.data_field_id == latest_subq.c.data_field_id,
                    DataFieldEntry.date == latest_subq.c.max_date,
                ),
            )
            .all()
        )
        latest_entry_map = {e.data_field_id: e for e in latest_entries}

        # Batch: get room assignments for all fields
        room_assignments = (
            db.query(DataFieldRoom.data_field_id, Room.id, Room.name)
            .join(Room, DataFieldRoom.room_id == Room.id)
            .filter(DataFieldRoom.data_field_id.in_(field_ids))
            .all()
        )
        # Build field_id -> list of (room_id, room_name) map
        field_rooms_map: dict[UUID, list[tuple[UUID, str]]] = {}
        for fid, rid, rname in room_assignments:
            field_rooms_map.setdefault(fid, []).append((rid, rname))

        # Batch: get room paths for all unique rooms
        all_room_ids_set = set()
        for rooms_list in field_rooms_map.values():
            for rid, _ in rooms_list:
                all_room_ids_set.add(rid)
        room_path_map: dict[UUID, str] = {}
        if all_room_ids_set:
            all_rooms = db.query(Room).filter(Room.id.in_(all_room_ids_set)).all()
            for room in all_rooms:
                ancestors = RoomService.get_ancestors(db, room)
                path_parts = [a.name for a in ancestors] + [room.name]
                room_path_map[room.id] = " > ".join(path_parts)

        result = []
        for field in fields:
            rooms_info = field_rooms_map.get(field.id, [])
            room_ids_list = [rid for rid, _ in rooms_info]
            room_names_list = [rname for _, rname in rooms_info]
            room_paths_list = [room_path_map.get(rid, "") for rid in room_ids_list]

            kpi_count = kpi_count_map.get(field.id, 0)
            latest_entry = latest_entry_map.get(field.id)

            result.append({
                "id": field.id,
                "org_id": field.org_id,
                "room_ids": room_ids_list,
                "room_names": room_names_list,
                "room_paths": room_paths_list,
                "name": field.name,
                "variable_name": field.variable_name,
                "description": field.description,
                "unit": field.unit,
                "entry_interval": field.entry_interval,
                "created_by": field.created_by,
                "created_at": field.created_at,
                "kpi_count": kpi_count,
                "latest_value": latest_entry.value if latest_entry else None,
                "latest_date": latest_entry.date if latest_entry else None,
            })

        return result
