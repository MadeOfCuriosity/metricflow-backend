from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import User, Room, UserRoomAssignment


class UserService:
    """Service for user management operations."""

    @staticmethod
    def get_all_users(db: Session, org_id: UUID) -> List[User]:
        """Get all users in an organization."""
        return db.query(User).filter(User.org_id == org_id).order_by(User.created_at.desc()).all()

    @staticmethod
    def get_user_by_id(db: Session, user_id: UUID, org_id: UUID) -> Optional[User]:
        """Get a user by ID within an organization."""
        return db.query(User).filter(
            User.id == user_id,
            User.org_id == org_id
        ).first()

    @staticmethod
    def get_user_with_rooms(db: Session, user_id: UUID) -> dict:
        """Get user with their assigned rooms."""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None

        # Get assigned rooms
        assignments = db.query(UserRoomAssignment).filter(
            UserRoomAssignment.user_id == user_id
        ).all()

        rooms = []
        for assignment in assignments:
            room = db.query(Room).filter(Room.id == assignment.room_id).first()
            if room:
                rooms.append({"id": room.id, "name": room.name})

        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "role_label": user.role_label,
            "created_at": user.created_at,
            "assigned_rooms": rooms,
        }

    @staticmethod
    def get_users_with_rooms(db: Session, org_id: UUID) -> List[dict]:
        """Get all users with their assigned rooms."""
        users = db.query(User).filter(User.org_id == org_id).order_by(User.created_at.desc()).all()

        result = []
        for user in users:
            user_data = UserService.get_user_with_rooms(db, user.id)
            if user_data:
                result.append(user_data)

        return result

    @staticmethod
    def assign_rooms_to_user(
        db: Session,
        user_id: UUID,
        room_ids: List[UUID],
        assigned_by: UUID,
        org_id: UUID,
    ) -> List[UserRoomAssignment]:
        """
        Assign rooms to a user. Replaces existing assignments.
        """
        # Verify user exists and belongs to org
        user = db.query(User).filter(
            User.id == user_id,
            User.org_id == org_id
        ).first()
        if not user:
            raise ValueError("User not found")

        # Remove existing assignments
        db.query(UserRoomAssignment).filter(
            UserRoomAssignment.user_id == user_id
        ).delete()

        # Create new assignments
        assignments = []
        for room_id in room_ids:
            # Verify room exists and belongs to org
            room = db.query(Room).filter(
                Room.id == room_id,
                Room.org_id == org_id
            ).first()
            if not room:
                raise ValueError(f"Room {room_id} not found")

            assignment = UserRoomAssignment(
                user_id=user_id,
                room_id=room_id,
                assigned_by=assigned_by,
            )
            db.add(assignment)
            assignments.append(assignment)

        db.commit()
        return assignments

    @staticmethod
    def add_room_to_user(
        db: Session,
        user_id: UUID,
        room_id: UUID,
        assigned_by: UUID,
    ) -> UserRoomAssignment:
        """Add a single room assignment to a user."""
        # Check if assignment already exists
        existing = db.query(UserRoomAssignment).filter(
            UserRoomAssignment.user_id == user_id,
            UserRoomAssignment.room_id == room_id
        ).first()

        if existing:
            return existing

        assignment = UserRoomAssignment(
            user_id=user_id,
            room_id=room_id,
            assigned_by=assigned_by,
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        return assignment

    @staticmethod
    def remove_room_from_user(db: Session, user_id: UUID, room_id: UUID) -> bool:
        """Remove a room assignment from a user."""
        result = db.query(UserRoomAssignment).filter(
            UserRoomAssignment.user_id == user_id,
            UserRoomAssignment.room_id == room_id
        ).delete()
        db.commit()
        return result > 0

    @staticmethod
    def update_user_role(
        db: Session,
        user_id: UUID,
        role: str,
        room_ids: Optional[List[UUID]],
        assigned_by: UUID,
        org_id: UUID,
    ) -> User:
        """Update a user's role and optionally their room assignments."""
        user = db.query(User).filter(
            User.id == user_id,
            User.org_id == org_id
        ).first()

        if not user:
            raise ValueError("User not found")

        user.role = role

        # If changing to room_admin, room_ids are required
        if role == "room_admin":
            if not room_ids:
                raise ValueError("Room assignments required for room_admin role")
            UserService.assign_rooms_to_user(db, user_id, room_ids, assigned_by, org_id)
        elif role == "admin":
            # Remove all room assignments for admins (they have access to all)
            db.query(UserRoomAssignment).filter(
                UserRoomAssignment.user_id == user_id
            ).delete()

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def delete_user(db: Session, user_id: UUID, org_id: UUID) -> bool:
        """Delete a user from the organization."""
        result = db.query(User).filter(
            User.id == user_id,
            User.org_id == org_id
        ).delete()
        db.commit()
        return result > 0

    @staticmethod
    def get_user_room_ids(db: Session, user_id: UUID) -> List[UUID]:
        """Get list of room IDs assigned to a user."""
        assignments = db.query(UserRoomAssignment.room_id).filter(
            UserRoomAssignment.user_id == user_id
        ).all()
        return [a.room_id for a in assignments]
