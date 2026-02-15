from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Room, RoomKPIAssignment, KPIDefinition, User, UserRoomAssignment
from app.schemas.rooms import RoomCreateRequest, RoomUpdateRequest


class RoomService:
    """Service for handling Room business logic."""

    @staticmethod
    def get_all_rooms(db: Session, org_id: UUID) -> list[Room]:
        """Get all rooms for an organization (flat list)."""
        return db.query(Room).filter(
            Room.org_id == org_id
        ).order_by(Room.name).all()

    @staticmethod
    def get_root_rooms(db: Session, org_id: UUID) -> list[Room]:
        """Get all top-level rooms (no parent) for an organization."""
        return db.query(Room).filter(
            Room.org_id == org_id,
            Room.parent_room_id == None
        ).order_by(Room.name).all()

    @staticmethod
    def get_accessible_rooms(db: Session, org_id: UUID, user: User) -> list[Room]:
        """
        Get rooms accessible to a user.
        Admins get all rooms, room_admins get only assigned rooms.
        """
        if user.role == "admin":
            return RoomService.get_all_rooms(db, org_id)

        # Get assigned room IDs for room_admin
        assigned_room_ids = [
            a.room_id for a in db.query(UserRoomAssignment).filter(
                UserRoomAssignment.user_id == user.id
            ).all()
        ]

        if not assigned_room_ids:
            return []

        return db.query(Room).filter(
            Room.org_id == org_id,
            Room.id.in_(assigned_room_ids)
        ).order_by(Room.name).all()

    @staticmethod
    def get_user_accessible_room_ids(db: Session, user: User) -> Optional[List[UUID]]:
        """
        Get list of room IDs a user has access to.
        Returns None for admins (meaning all rooms).
        """
        if user.role == "admin":
            return None

        return [
            a.room_id for a in db.query(UserRoomAssignment).filter(
                UserRoomAssignment.user_id == user.id
            ).all()
        ]

    @staticmethod
    def get_room_by_id(
        db: Session,
        room_id: UUID,
        org_id: UUID
    ) -> Optional[Room]:
        """Get a single room by ID, ensuring it belongs to the org."""
        return db.query(Room).filter(
            Room.id == room_id,
            Room.org_id == org_id
        ).first()

    @staticmethod
    def get_room_tree(db: Session, org_id: UUID, user: Optional[User] = None) -> list[dict]:
        """
        Get rooms as a nested tree structure.
        Returns list of root rooms with nested children.
        For room_admins, returns only assigned rooms (as flat list, not nested).
        """
        # For room_admin, return only assigned rooms as flat list
        if user and user.role == "room_admin":
            accessible_rooms = RoomService.get_accessible_rooms(db, org_id, user)
            result = []
            for room in accessible_rooms:
                kpi_count = db.query(RoomKPIAssignment).filter(
                    RoomKPIAssignment.room_id == room.id
                ).count()
                result.append({
                    "id": room.id,
                    "name": room.name,
                    "description": room.description,
                    "children": [],
                    "kpi_count": kpi_count,
                })
            return result

        # For admins, return full tree
        all_rooms = RoomService.get_all_rooms(db, org_id)

        # Build room lookup and count KPIs
        room_lookup = {}
        for room in all_rooms:
            kpi_count = db.query(RoomKPIAssignment).filter(
                RoomKPIAssignment.room_id == room.id
            ).count()
            room_lookup[room.id] = {
                "id": room.id,
                "name": room.name,
                "description": room.description,
                "parent_room_id": room.parent_room_id,
                "children": [],
                "kpi_count": kpi_count,
            }

        # Build tree structure
        root_rooms = []
        for room_id, room_data in room_lookup.items():
            parent_id = room_data["parent_room_id"]
            if parent_id is None:
                root_rooms.append(room_data)
            elif parent_id in room_lookup:
                room_lookup[parent_id]["children"].append(room_data)

        # Remove parent_room_id from output (not needed in tree)
        def clean_tree(nodes):
            for node in nodes:
                del node["parent_room_id"]
                clean_tree(node["children"])
        clean_tree(root_rooms)

        return root_rooms

    @staticmethod
    def create_room(
        db: Session,
        org_id: UUID,
        user_id: UUID,
        data: RoomCreateRequest,
    ) -> Room:
        """Create a new room or sub-room."""
        # Validate parent room if specified
        if data.parent_room_id:
            parent = RoomService.get_room_by_id(db, data.parent_room_id, org_id)
            if not parent:
                raise ValueError("Parent room not found")

        room = Room(
            org_id=org_id,
            name=data.name,
            description=data.description,
            parent_room_id=data.parent_room_id,
            created_by=user_id,
        )
        db.add(room)
        db.commit()
        db.refresh(room)
        return room

    @staticmethod
    def update_room(
        db: Session,
        room: Room,
        data: RoomUpdateRequest,
    ) -> Room:
        """Update an existing room."""
        if data.name is not None:
            room.name = data.name
        if data.description is not None:
            room.description = data.description

        db.commit()
        db.refresh(room)
        return room

    @staticmethod
    def delete_room(db: Session, room: Room) -> bool:
        """
        Delete a room and all its sub-rooms (cascade).
        Returns True if deleted.
        """
        db.delete(room)
        db.commit()
        return True

    @staticmethod
    def get_room_with_counts(db: Session, room: Room) -> dict:
        """Get room with KPI count and sub-room count."""
        kpi_count = db.query(RoomKPIAssignment).filter(
            RoomKPIAssignment.room_id == room.id
        ).count()

        sub_room_count = db.query(Room).filter(
            Room.parent_room_id == room.id
        ).count()

        return {
            "id": room.id,
            "org_id": room.org_id,
            "name": room.name,
            "description": room.description,
            "parent_room_id": room.parent_room_id,
            "created_by": room.created_by,
            "created_at": room.created_at,
            "kpi_count": kpi_count,
            "sub_room_count": sub_room_count,
        }

    @staticmethod
    def assign_kpis_to_room(
        db: Session,
        room: Room,
        kpi_ids: list[UUID],
        user_id: UUID,
        org_id: UUID,
    ) -> list[RoomKPIAssignment]:
        """Assign KPIs to a room."""
        assignments = []

        for kpi_id in kpi_ids:
            # Verify KPI belongs to org
            kpi = db.query(KPIDefinition).filter(
                KPIDefinition.id == kpi_id,
                KPIDefinition.org_id == org_id
            ).first()

            if not kpi:
                continue  # Skip invalid KPIs

            # Check if already assigned
            existing = db.query(RoomKPIAssignment).filter(
                RoomKPIAssignment.room_id == room.id,
                RoomKPIAssignment.kpi_id == kpi_id
            ).first()

            if existing:
                continue  # Already assigned

            assignment = RoomKPIAssignment(
                room_id=room.id,
                kpi_id=kpi_id,
                assigned_by=user_id,
            )
            db.add(assignment)
            assignments.append(assignment)

        if assignments:
            db.commit()
            for assignment in assignments:
                db.refresh(assignment)

        return assignments

    @staticmethod
    def remove_kpi_from_room(
        db: Session,
        room: Room,
        kpi_id: UUID,
    ) -> bool:
        """Remove a KPI from a room."""
        assignment = db.query(RoomKPIAssignment).filter(
            RoomKPIAssignment.room_id == room.id,
            RoomKPIAssignment.kpi_id == kpi_id
        ).first()

        if not assignment:
            return False

        db.delete(assignment)
        db.commit()
        return True

    @staticmethod
    def get_all_descendant_ids(db: Session, room_id: UUID) -> list[UUID]:
        """
        Recursively collect all descendant room IDs for a given room.
        Returns IDs of children, grandchildren, etc. at unlimited depth.
        """
        descendant_ids = []
        queue = [room_id]
        while queue:
            parent_id = queue.pop(0)
            child_ids = [
                cid for (cid,) in db.query(Room.id).filter(
                    Room.parent_room_id == parent_id
                ).all()
            ]
            descendant_ids.extend(child_ids)
            queue.extend(child_ids)
        return descendant_ids

    @staticmethod
    def get_room_kpis(
        db: Session,
        room_id: UUID,
        org_id: UUID,
    ) -> tuple[list[KPIDefinition], list[KPIDefinition], list[KPIDefinition]]:
        """
        Get KPIs for a room.
        Returns (room_specific_kpis, descendant_kpis, shared_kpis).
        descendant_kpis contains KPIs from all descendants (children, grandchildren, etc.).
        Children do NOT inherit parent KPIs — only see their own + their descendants'.
        """
        # Get room-specific KPIs
        room_kpi_ids = [
            kpi_id for (kpi_id,) in db.query(RoomKPIAssignment.kpi_id).filter(
                RoomKPIAssignment.room_id == room_id
            ).all()
        ]

        room_kpis = db.query(KPIDefinition).filter(
            KPIDefinition.id.in_(room_kpi_ids)
        ).order_by(KPIDefinition.category, KPIDefinition.name).all() if room_kpi_ids else []

        # Get descendant KPIs (from all children, grandchildren, etc.)
        sub_room_kpis = []
        descendant_ids = RoomService.get_all_descendant_ids(db, room_id)
        if descendant_ids:
            # Get all KPI IDs from descendants, excluding already-assigned ones
            sub_kpi_ids = [
                kpi_id for (kpi_id,) in db.query(RoomKPIAssignment.kpi_id).filter(
                    RoomKPIAssignment.room_id.in_(descendant_ids),
                    ~RoomKPIAssignment.kpi_id.in_(room_kpi_ids) if room_kpi_ids else True
                ).distinct().all()
            ]
            if sub_kpi_ids:
                sub_room_kpis = db.query(KPIDefinition).filter(
                    KPIDefinition.id.in_(sub_kpi_ids)
                ).order_by(KPIDefinition.category, KPIDefinition.name).all()

        # Get shared (org-wide) KPIs
        shared_kpis = db.query(KPIDefinition).filter(
            KPIDefinition.org_id == org_id,
            KPIDefinition.is_shared == True
        ).order_by(KPIDefinition.category, KPIDefinition.name).all()

        return room_kpis, sub_room_kpis, shared_kpis

    @staticmethod
    def get_ancestors(db: Session, room: Room) -> list[Room]:
        """
        Get all ancestor rooms (parent chain) for breadcrumb navigation.
        Returns list from root to immediate parent.
        """
        ancestors = []
        current = room

        while current.parent_room_id:
            parent = db.query(Room).filter(Room.id == current.parent_room_id).first()
            if parent:
                ancestors.insert(0, parent)
                current = parent
            else:
                break

        return ancestors

    @staticmethod
    def check_room_name_exists(
        db: Session,
        org_id: UUID,
        name: str,
        parent_room_id: Optional[UUID] = None,
        exclude_id: Optional[UUID] = None
    ) -> bool:
        """Check if a room with the given name already exists at the same level."""
        query = db.query(Room).filter(
            Room.org_id == org_id,
            Room.name == name,
            Room.parent_room_id == parent_room_id
        )
        if exclude_id:
            query = query.filter(Room.id != exclude_id)
        return query.first() is not None
