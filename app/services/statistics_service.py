"""
Statistics service for KPI data analysis.
"""
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import DataEntry, KPIDefinition


@dataclass
class KPIStatistics:
    """Statistical summary for a KPI."""
    kpi_id: UUID
    kpi_name: str
    period_days: int
    data_points: int
    mean: Optional[float]
    median: Optional[float]
    std_dev: Optional[float]
    min_value: Optional[float]
    max_value: Optional[float]
    percentile_25: Optional[float]
    percentile_75: Optional[float]
    percentile_90: Optional[float]
    current_value: Optional[float]
    all_time_high: Optional[float]
    all_time_low: Optional[float]


@dataclass
class TrendResult:
    """Result of trend analysis."""
    direction: str  # "increasing", "decreasing", "stable"
    consecutive_count: int  # Number of consecutive entries in same direction
    percentage_change: Optional[float]  # Overall change from first to last


@dataclass
class AnomalyResult:
    """Result of anomaly detection."""
    is_anomaly: bool
    deviation_type: Optional[str]  # "high" or "low"
    std_devs_from_mean: Optional[float]
    message: Optional[str]


class StatisticsService:
    """Service for calculating KPI statistics and detecting patterns."""

    @staticmethod
    def calculate_stats(
        db: Session,
        org_id: UUID,
        kpi_id: UUID,
        period_days: int = 30,
    ) -> Optional[KPIStatistics]:
        """
        Calculate comprehensive statistics for a KPI over a period.

        Args:
            db: Database session
            org_id: Organization ID
            kpi_id: KPI ID
            period_days: Number of days to analyze

        Returns:
            KPIStatistics object or None if KPI not found
        """
        # Get the KPI
        kpi = db.query(KPIDefinition).filter(
            KPIDefinition.id == kpi_id,
            KPIDefinition.org_id == org_id
        ).first()

        if not kpi:
            return None

        # Calculate date range
        end_date = date.today()
        start_date = end_date - timedelta(days=period_days)

        # Get entries for the period
        entries = db.query(DataEntry).filter(
            DataEntry.org_id == org_id,
            DataEntry.kpi_id == kpi_id,
            DataEntry.date >= start_date,
            DataEntry.date <= end_date
        ).order_by(DataEntry.date.desc()).all()

        values = [e.calculated_value for e in entries]

        # Get all-time high/low
        all_time_stats = db.query(
            func.max(DataEntry.calculated_value),
            func.min(DataEntry.calculated_value)
        ).filter(
            DataEntry.org_id == org_id,
            DataEntry.kpi_id == kpi_id
        ).first()

        all_time_high = all_time_stats[0] if all_time_stats else None
        all_time_low = all_time_stats[1] if all_time_stats else None

        if not values:
            return KPIStatistics(
                kpi_id=kpi_id,
                kpi_name=kpi.name,
                period_days=period_days,
                data_points=0,
                mean=None,
                median=None,
                std_dev=None,
                min_value=None,
                max_value=None,
                percentile_25=None,
                percentile_75=None,
                percentile_90=None,
                current_value=None,
                all_time_high=all_time_high,
                all_time_low=all_time_low,
            )

        # Calculate statistics
        mean = round(statistics.mean(values), 4)
        median = round(statistics.median(values), 4)
        min_value = round(min(values), 4)
        max_value = round(max(values), 4)
        current_value = round(values[0], 4)  # Most recent

        std_dev = None
        if len(values) >= 2:
            std_dev = round(statistics.stdev(values), 4)

        # Calculate percentiles
        sorted_values = sorted(values)
        percentile_25 = StatisticsService._percentile(sorted_values, 25)
        percentile_75 = StatisticsService._percentile(sorted_values, 75)
        percentile_90 = StatisticsService._percentile(sorted_values, 90)

        return KPIStatistics(
            kpi_id=kpi_id,
            kpi_name=kpi.name,
            period_days=period_days,
            data_points=len(values),
            mean=mean,
            median=median,
            std_dev=std_dev,
            min_value=min_value,
            max_value=max_value,
            percentile_25=percentile_25,
            percentile_75=percentile_75,
            percentile_90=percentile_90,
            current_value=current_value,
            all_time_high=round(all_time_high, 4) if all_time_high else None,
            all_time_low=round(all_time_low, 4) if all_time_low else None,
        )

    @staticmethod
    def _percentile(sorted_values: list[float], percentile: int) -> Optional[float]:
        """Calculate percentile from sorted values."""
        if not sorted_values:
            return None
        n = len(sorted_values)
        index = (percentile / 100) * (n - 1)
        lower = int(index)
        upper = lower + 1
        if upper >= n:
            return round(sorted_values[-1], 4)
        weight = index - lower
        return round(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight, 4)

    @staticmethod
    def detect_anomaly(
        value: float,
        mean: float,
        std_dev: Optional[float],
        threshold_std_devs: float = 1.5,
    ) -> AnomalyResult:
        """
        Detect if a value is an anomaly based on standard deviation.

        Args:
            value: The value to check
            mean: The mean of the dataset
            std_dev: Standard deviation of the dataset
            threshold_std_devs: Number of std devs to consider anomaly (default 1.5)

        Returns:
            AnomalyResult with detection info
        """
        if std_dev is None or std_dev == 0:
            return AnomalyResult(
                is_anomaly=False,
                deviation_type=None,
                std_devs_from_mean=None,
                message=None
            )

        std_devs_from_mean = (value - mean) / std_dev

        if abs(std_devs_from_mean) > threshold_std_devs:
            deviation_type = "high" if std_devs_from_mean > 0 else "low"
            return AnomalyResult(
                is_anomaly=True,
                deviation_type=deviation_type,
                std_devs_from_mean=round(std_devs_from_mean, 2),
                message=f"Value is {abs(round(std_devs_from_mean, 1))} standard deviations {'above' if deviation_type == 'high' else 'below'} the mean"
            )

        return AnomalyResult(
            is_anomaly=False,
            deviation_type=None,
            std_devs_from_mean=round(std_devs_from_mean, 2),
            message=None
        )

    @staticmethod
    def calculate_trend(values: list[float], min_points: int = 3) -> TrendResult:
        """
        Calculate the trend direction from a list of values.

        Args:
            values: List of values (most recent first)
            min_points: Minimum points needed for trend analysis

        Returns:
            TrendResult with direction and details
        """
        if len(values) < min_points:
            return TrendResult(
                direction="stable",
                consecutive_count=0,
                percentage_change=None
            )

        # Reverse to get chronological order (oldest first)
        chronological = list(reversed(values))

        # Count consecutive increases/decreases from the end
        consecutive_increasing = 0
        consecutive_decreasing = 0

        for i in range(len(chronological) - 1, 0, -1):
            if chronological[i] > chronological[i - 1]:
                consecutive_increasing += 1
                consecutive_decreasing = 0
            elif chronological[i] < chronological[i - 1]:
                consecutive_decreasing += 1
                consecutive_increasing = 0
            else:
                break

        # Calculate overall percentage change
        percentage_change = None
        if chronological[0] != 0:
            percentage_change = round(
                ((chronological[-1] - chronological[0]) / abs(chronological[0])) * 100,
                2
            )

        # Determine trend direction
        if consecutive_increasing >= min_points - 1:
            return TrendResult(
                direction="increasing",
                consecutive_count=consecutive_increasing + 1,
                percentage_change=percentage_change
            )
        elif consecutive_decreasing >= min_points - 1:
            return TrendResult(
                direction="decreasing",
                consecutive_count=consecutive_decreasing + 1,
                percentage_change=percentage_change
            )
        else:
            return TrendResult(
                direction="stable",
                consecutive_count=0,
                percentage_change=percentage_change
            )

    @staticmethod
    def get_last_entry_date(
        db: Session,
        org_id: UUID,
        kpi_id: UUID,
    ) -> Optional[date]:
        """Get the date of the last entry for a KPI."""
        entry = db.query(DataEntry).filter(
            DataEntry.org_id == org_id,
            DataEntry.kpi_id == kpi_id
        ).order_by(DataEntry.date.desc()).first()

        return entry.date if entry else None

    @staticmethod
    def get_recent_values(
        db: Session,
        org_id: UUID,
        kpi_id: UUID,
        limit: int = 10,
    ) -> list[tuple[date, float]]:
        """Get recent values for a KPI as (date, value) tuples."""
        entries = db.query(DataEntry).filter(
            DataEntry.org_id == org_id,
            DataEntry.kpi_id == kpi_id
        ).order_by(DataEntry.date.desc()).limit(limit).all()

        return [(e.date, e.calculated_value) for e in entries]
