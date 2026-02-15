from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, distinct
from sqlalchemy.orm import Session

from app.models import (
    User,
    KPIDefinition,
    Room,
    DataEntry,
    Integration,
    SyncLog,
)


class AdminStatsService:
    """Service for aggregating admin dashboard statistics."""

    @staticmethod
    def get_org_stats(db: Session, org_id: UUID) -> dict:
        """Get aggregated counts for the admin dashboard."""
        today = date.today()

        total_users = db.query(func.count(User.id)).filter(
            User.org_id == org_id
        ).scalar() or 0

        total_kpis = db.query(func.count(KPIDefinition.id)).filter(
            KPIDefinition.org_id == org_id
        ).scalar() or 0

        total_rooms = db.query(func.count(Room.id)).filter(
            Room.org_id == org_id
        ).scalar() or 0

        active_integrations = db.query(func.count(Integration.id)).filter(
            Integration.org_id == org_id,
            Integration.status == "connected",
        ).scalar() or 0

        total_data_entries = db.query(func.count(DataEntry.id)).filter(
            DataEntry.org_id == org_id
        ).scalar() or 0

        today_data_entries = db.query(func.count(DataEntry.id)).filter(
            DataEntry.org_id == org_id,
            DataEntry.date == today,
        ).scalar() or 0

        return {
            "total_users": total_users,
            "total_kpis": total_kpis,
            "total_rooms": total_rooms,
            "active_integrations": active_integrations,
            "total_data_entries": total_data_entries,
            "today_data_entries": today_data_entries,
        }

    @staticmethod
    def get_completion_rates(db: Session, org_id: UUID, days: int = 30) -> list[dict]:
        """Calculate daily data entry completion rates for the last N days."""
        today = date.today()

        total_kpis = db.query(func.count(KPIDefinition.id)).filter(
            KPIDefinition.org_id == org_id
        ).scalar() or 0

        if total_kpis == 0:
            return [
                {"date": (today - timedelta(days=i)).isoformat(), "rate": 0.0}
                for i in range(days - 1, -1, -1)
            ]

        start_date = today - timedelta(days=days - 1)

        # Get entry counts per day in one query
        daily_counts = (
            db.query(
                DataEntry.date,
                func.count(distinct(DataEntry.kpi_id)),
            )
            .filter(
                DataEntry.org_id == org_id,
                DataEntry.date >= start_date,
                DataEntry.date <= today,
            )
            .group_by(DataEntry.date)
            .all()
        )

        counts_map = {row[0]: row[1] for row in daily_counts}

        rates = []
        for i in range(days):
            d = start_date + timedelta(days=i)
            count = counts_map.get(d, 0)
            rate = round(min((count / total_kpis) * 100, 100.0), 1)
            rates.append({"date": d.isoformat(), "rate": rate})

        return rates

    @staticmethod
    def get_activity_feed(
        db: Session, org_id: UUID, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Get recent activity across all entity types."""
        activities = []

        # Recent data entries
        recent_entries = (
            db.query(DataEntry, User.name, KPIDefinition.name)
            .join(User, DataEntry.entered_by == User.id, isouter=True)
            .join(KPIDefinition, DataEntry.kpi_id == KPIDefinition.id)
            .filter(DataEntry.org_id == org_id)
            .order_by(DataEntry.created_at.desc())
            .limit(100)
            .all()
        )
        for entry, user_name, kpi_name in recent_entries:
            activities.append({
                "id": str(entry.id),
                "type": "data_entry",
                "description": f"Submitted data for {kpi_name}",
                "user_name": user_name,
                "timestamp": entry.created_at,
                "metadata": {"kpi_name": kpi_name, "date": entry.date.isoformat()},
            })

        # Recent users joined
        recent_users = (
            db.query(User)
            .filter(User.org_id == org_id)
            .order_by(User.created_at.desc())
            .limit(50)
            .all()
        )
        for user in recent_users:
            activities.append({
                "id": f"user-{user.id}",
                "type": "user_joined",
                "description": f"{user.name} joined the organization",
                "user_name": user.name,
                "timestamp": user.created_at,
                "metadata": {"role": user.role, "email": user.email},
            })

        # Recent KPIs created
        recent_kpis = (
            db.query(KPIDefinition, User.name)
            .join(User, KPIDefinition.created_by == User.id, isouter=True)
            .filter(KPIDefinition.org_id == org_id)
            .order_by(KPIDefinition.created_at.desc())
            .limit(50)
            .all()
        )
        for kpi, creator_name in recent_kpis:
            activities.append({
                "id": f"kpi-{kpi.id}",
                "type": "kpi_created",
                "description": f"KPI \"{kpi.name}\" was created",
                "user_name": creator_name,
                "timestamp": kpi.created_at,
                "metadata": {"kpi_name": kpi.name, "category": kpi.category},
            })

        # Recent rooms created
        recent_rooms = (
            db.query(Room, User.name)
            .join(User, Room.created_by == User.id, isouter=True)
            .filter(Room.org_id == org_id)
            .order_by(Room.created_at.desc())
            .limit(50)
            .all()
        )
        for room, creator_name in recent_rooms:
            activities.append({
                "id": f"room-{room.id}",
                "type": "room_created",
                "description": f"Room \"{room.name}\" was created",
                "user_name": creator_name,
                "timestamp": room.created_at,
                "metadata": {"room_name": room.name},
            })

        # Recent integration syncs
        recent_syncs = (
            db.query(SyncLog, Integration.display_name, User.name)
            .join(Integration, SyncLog.integration_id == Integration.id)
            .join(User, SyncLog.triggered_by == User.id, isouter=True)
            .filter(Integration.org_id == org_id)
            .order_by(SyncLog.started_at.desc())
            .limit(50)
            .all()
        )
        for sync, integration_name, user_name in recent_syncs:
            status_text = "completed" if sync.status == "success" else sync.status
            activities.append({
                "id": f"sync-{sync.id}",
                "type": "integration_synced",
                "description": f"Sync {status_text} for {integration_name}",
                "user_name": user_name,
                "timestamp": sync.started_at,
                "metadata": {
                    "integration_name": integration_name,
                    "status": sync.status,
                    "rows_written": sync.rows_written,
                },
            })

        # Sort all activities by timestamp descending
        activities.sort(key=lambda a: a["timestamp"], reverse=True)

        total = len(activities)
        paginated = activities[offset : offset + limit]

        return paginated, total
