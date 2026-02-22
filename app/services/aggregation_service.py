"""
Service for aggregating KPI data from sub-rooms to parent rooms.
"""
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DataEntry, Room
from app.services.room_service import RoomService


class AggregationService:
    """Compute-on-read aggregation of KPI values across descendant rooms."""

    @staticmethod
    def get_aggregated_entries(
        db: Session,
        org_id: UUID,
        kpi_id: UUID,
        room_id: UUID,
        method: str = "sum",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 365,
    ) -> list[dict]:
        """
        Get time-series aggregated values for a KPI across descendant rooms.

        Returns list of {date, aggregated_value, sub_room_count} dicts,
        ordered by date descending.
        """
        descendant_ids = RoomService.get_all_descendant_ids(db, room_id)
        if not descendant_ids:
            return []

        agg_func = func.sum(DataEntry.calculated_value)
        if method == "avg":
            agg_func = func.avg(DataEntry.calculated_value)

        query = db.query(
            DataEntry.date,
            agg_func.label("aggregated_value"),
            func.count(DataEntry.id).label("sub_room_count"),
        ).filter(
            DataEntry.org_id == org_id,
            DataEntry.kpi_id == kpi_id,
            DataEntry.room_id.in_(descendant_ids),
        ).group_by(DataEntry.date).order_by(DataEntry.date.desc())

        if start_date:
            query = query.filter(DataEntry.date >= start_date)
        if end_date:
            query = query.filter(DataEntry.date <= end_date)

        results = query.limit(limit).all()

        return [
            {
                "date": r.date,
                "aggregated_value": round(float(r.aggregated_value), 4) if r.aggregated_value is not None else 0.0,
                "sub_room_count": r.sub_room_count,
            }
            for r in results
        ]

    @staticmethod
    def get_sub_room_breakdown(
        db: Session,
        org_id: UUID,
        kpi_id: UUID,
        room_id: UUID,
        target_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Get per-sub-room values for a KPI on a specific date (or latest available).

        Returns breakdown showing each sub-room's contribution.
        """
        descendant_ids = RoomService.get_all_descendant_ids(db, room_id)
        if not descendant_ids:
            return []

        query = db.query(DataEntry).filter(
            DataEntry.org_id == org_id,
            DataEntry.kpi_id == kpi_id,
            DataEntry.room_id.in_(descendant_ids),
        )

        if target_date:
            query = query.filter(DataEntry.date == target_date)
        else:
            # Get latest date that has data
            latest = db.query(func.max(DataEntry.date)).filter(
                DataEntry.org_id == org_id,
                DataEntry.kpi_id == kpi_id,
                DataEntry.room_id.in_(descendant_ids),
            ).scalar()
            if not latest:
                return []
            query = query.filter(DataEntry.date == latest)

        entries = query.all()

        result = []
        for entry in entries:
            room = db.query(Room).filter(Room.id == entry.room_id).first()
            result.append({
                "room_id": str(entry.room_id),
                "room_name": room.name if room else "Unknown",
                "value": entry.calculated_value,
            })

        return result
