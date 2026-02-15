"""
Insight generator for automatic KPI analysis.
"""
from datetime import datetime, date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Insight, KPIDefinition, DataEntry
from app.services.statistics_service import StatisticsService


class InsightGenerator:
    """Service for generating insights from KPI data."""

    # Priority levels
    PRIORITY_HIGH = "high"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_LOW = "low"

    # Thresholds
    DEVIATION_THRESHOLD = 0.20  # 20% deviation from average
    CONSECUTIVE_TREND_DAYS = 4  # Days for trend detection
    MISSING_DATA_DAYS = 3  # Days without data
    STD_DEV_THRESHOLD = 1.5  # Standard deviations for anomaly

    @staticmethod
    def generate_insights(db: Session, org_id: UUID) -> list[Insight]:
        """
        Generate insights for all KPIs in an organization.

        Args:
            db: Database session
            org_id: Organization ID

        Returns:
            List of generated Insight objects
        """
        insights = []

        # Get all KPIs for the organization
        kpis = db.query(KPIDefinition).filter(
            KPIDefinition.org_id == org_id
        ).all()

        for kpi in kpis:
            kpi_insights = InsightGenerator._analyze_kpi(db, org_id, kpi)
            insights.extend(kpi_insights)

        # Clear old insights and save new ones
        InsightGenerator._save_insights(db, org_id, insights)

        return insights

    @staticmethod
    def _analyze_kpi(
        db: Session,
        org_id: UUID,
        kpi: KPIDefinition,
    ) -> list[Insight]:
        """Analyze a single KPI and generate insights."""
        insights = []

        # Get statistics for 30-day period
        stats = StatisticsService.calculate_stats(db, org_id, kpi.id, period_days=30)

        if not stats or stats.data_points == 0:
            # Check for missing data
            insight = InsightGenerator._check_no_data(db, org_id, kpi)
            if insight:
                insights.append(insight)
            return insights

        # Get recent values for trend analysis
        recent_values = StatisticsService.get_recent_values(db, org_id, kpi.id, limit=10)
        values_only = [v for _, v in recent_values]

        # 1. Check deviation from average
        deviation_insight = InsightGenerator._check_deviation_from_average(
            org_id, kpi, stats.current_value, stats.mean
        )
        if deviation_insight:
            insights.append(deviation_insight)

        # 2. Check for consecutive trend
        if len(values_only) >= InsightGenerator.CONSECUTIVE_TREND_DAYS:
            trend_insight = InsightGenerator._check_consecutive_trend(
                org_id, kpi, values_only
            )
            if trend_insight:
                insights.append(trend_insight)

        # 3. Check for all-time high/low
        record_insight = InsightGenerator._check_all_time_record(
            org_id, kpi, stats.current_value, stats.all_time_high, stats.all_time_low
        )
        if record_insight:
            insights.append(record_insight)

        # 4. Check for anomaly (outside normal range)
        anomaly_insight = InsightGenerator._check_anomaly(
            org_id, kpi, stats.current_value, stats.mean, stats.std_dev
        )
        if anomaly_insight:
            insights.append(anomaly_insight)

        # 5. Check for missing recent data
        last_entry_date = StatisticsService.get_last_entry_date(db, org_id, kpi.id)
        missing_insight = InsightGenerator._check_missing_data(
            org_id, kpi, last_entry_date
        )
        if missing_insight:
            insights.append(missing_insight)

        return insights

    @staticmethod
    def _check_deviation_from_average(
        org_id: UUID,
        kpi: KPIDefinition,
        current_value: float,
        mean: float,
    ) -> Optional[Insight]:
        """Check if current value deviates significantly from average."""
        if mean == 0:
            return None

        deviation = (current_value - mean) / abs(mean)

        if abs(deviation) >= InsightGenerator.DEVIATION_THRESHOLD:
            direction = "above" if deviation > 0 else "below"
            percentage = abs(round(deviation * 100, 1))

            return Insight(
                org_id=org_id,
                kpi_id=kpi.id,
                insight_text=f"{kpi.name} is {percentage}% {direction} your 30-day average",
                priority=InsightGenerator.PRIORITY_MEDIUM if percentage < 30 else InsightGenerator.PRIORITY_HIGH,
            )

        return None

    @staticmethod
    def _check_consecutive_trend(
        org_id: UUID,
        kpi: KPIDefinition,
        values: list[float],
    ) -> Optional[Insight]:
        """Check for consecutive increasing/decreasing trend."""
        trend = StatisticsService.calculate_trend(
            values,
            min_points=InsightGenerator.CONSECUTIVE_TREND_DAYS
        )

        if trend.direction == "increasing" and trend.consecutive_count >= InsightGenerator.CONSECUTIVE_TREND_DAYS:
            return Insight(
                org_id=org_id,
                kpi_id=kpi.id,
                insight_text=f"{kpi.name} has been trending up for {trend.consecutive_count} consecutive entries",
                priority=InsightGenerator.PRIORITY_LOW,
            )
        elif trend.direction == "decreasing" and trend.consecutive_count >= InsightGenerator.CONSECUTIVE_TREND_DAYS:
            return Insight(
                org_id=org_id,
                kpi_id=kpi.id,
                insight_text=f"{kpi.name} has been trending down for {trend.consecutive_count} consecutive entries",
                priority=InsightGenerator.PRIORITY_MEDIUM,
            )

        return None

    @staticmethod
    def _check_all_time_record(
        org_id: UUID,
        kpi: KPIDefinition,
        current_value: float,
        all_time_high: Optional[float],
        all_time_low: Optional[float],
    ) -> Optional[Insight]:
        """Check if current value is an all-time high or low."""
        if all_time_high is not None and current_value >= all_time_high:
            return Insight(
                org_id=org_id,
                kpi_id=kpi.id,
                insight_text=f"{kpi.name} hit an all-time high of {round(current_value, 2)}",
                priority=InsightGenerator.PRIORITY_HIGH,
            )

        if all_time_low is not None and current_value <= all_time_low:
            return Insight(
                org_id=org_id,
                kpi_id=kpi.id,
                insight_text=f"{kpi.name} hit an all-time low of {round(current_value, 2)}",
                priority=InsightGenerator.PRIORITY_HIGH,
            )

        return None

    @staticmethod
    def _check_anomaly(
        org_id: UUID,
        kpi: KPIDefinition,
        current_value: float,
        mean: float,
        std_dev: Optional[float],
    ) -> Optional[Insight]:
        """Check if current value is outside normal range."""
        anomaly = StatisticsService.detect_anomaly(
            current_value, mean, std_dev,
            threshold_std_devs=InsightGenerator.STD_DEV_THRESHOLD
        )

        if anomaly.is_anomaly:
            direction = "higher" if anomaly.deviation_type == "high" else "lower"
            return Insight(
                org_id=org_id,
                kpi_id=kpi.id,
                insight_text=f"{kpi.name} is outside normal range - significantly {direction} than usual ({anomaly.std_devs_from_mean} std devs)",
                priority=InsightGenerator.PRIORITY_HIGH,
            )

        return None

    @staticmethod
    def _check_missing_data(
        org_id: UUID,
        kpi: KPIDefinition,
        last_entry_date: Optional[date],
    ) -> Optional[Insight]:
        """Check if data hasn't been entered for several days."""
        if last_entry_date is None:
            return Insight(
                org_id=org_id,
                kpi_id=kpi.id,
                insight_text=f"No data has been entered for {kpi.name} yet",
                priority=InsightGenerator.PRIORITY_LOW,
            )

        days_since_entry = (date.today() - last_entry_date).days

        if days_since_entry >= InsightGenerator.MISSING_DATA_DAYS:
            return Insight(
                org_id=org_id,
                kpi_id=kpi.id,
                insight_text=f"You haven't entered data for {kpi.name} in {days_since_entry} days",
                priority=InsightGenerator.PRIORITY_MEDIUM,
            )

        return None

    @staticmethod
    def _check_no_data(
        db: Session,
        org_id: UUID,
        kpi: KPIDefinition,
    ) -> Optional[Insight]:
        """Check if KPI has no data at all."""
        count = db.query(DataEntry).filter(
            DataEntry.org_id == org_id,
            DataEntry.kpi_id == kpi.id
        ).count()

        if count == 0:
            return Insight(
                org_id=org_id,
                kpi_id=kpi.id,
                insight_text=f"Start tracking {kpi.name} by entering your first data point",
                priority=InsightGenerator.PRIORITY_LOW,
            )

        return None

    @staticmethod
    def _save_insights(
        db: Session,
        org_id: UUID,
        insights: list[Insight],
    ) -> None:
        """Clear old insights and save new ones."""
        # Delete existing insights for this org
        db.query(Insight).filter(Insight.org_id == org_id).delete()

        # Add new insights
        for insight in insights:
            db.add(insight)

        db.commit()

        # Refresh all insights to get their IDs
        for insight in insights:
            db.refresh(insight)

    @staticmethod
    def get_cached_insights(
        db: Session,
        org_id: UUID,
        max_age_hours: int = 24,
    ) -> tuple[list[Insight], bool]:
        """
        Get cached insights if they're fresh enough.

        Args:
            db: Database session
            org_id: Organization ID
            max_age_hours: Maximum age in hours before refresh needed

        Returns:
            Tuple of (insights list, needs_refresh bool)
        """
        insights = db.query(Insight).filter(
            Insight.org_id == org_id
        ).order_by(
            # Sort by priority (high first)
            Insight.priority.desc(),
            Insight.generated_at.desc()
        ).all()

        if not insights:
            return [], True

        # Check if oldest insight is too old
        oldest = min(insights, key=lambda i: i.generated_at)
        age = datetime.utcnow() - oldest.generated_at
        needs_refresh = age.total_seconds() > (max_age_hours * 3600)

        # Sort insights by priority
        priority_order = {
            InsightGenerator.PRIORITY_HIGH: 0,
            InsightGenerator.PRIORITY_MEDIUM: 1,
            InsightGenerator.PRIORITY_LOW: 2,
        }
        insights.sort(key=lambda i: (priority_order.get(i.priority, 3), i.generated_at), reverse=False)

        return insights, needs_refresh
