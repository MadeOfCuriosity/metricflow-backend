"""
Calculation service for safely computing KPI values.
"""
import statistics
from typing import Optional
from dataclasses import dataclass

from app.core.formula_parser import FormulaParser, FormulaError


@dataclass
class CalculationResult:
    """Result of a KPI calculation."""
    success: bool
    value: Optional[float]
    error: Optional[str]


@dataclass
class StatsSummary:
    """Statistical summary of KPI data."""
    current_value: Optional[float]
    mean: Optional[float]
    median: Optional[float]
    std_dev: Optional[float]
    min_value: Optional[float]
    max_value: Optional[float]
    trend: Optional[str]  # "up", "down", "stable"
    trend_percentage: Optional[float]
    data_points: int


class CalculationService:
    """Service for safely computing KPI values and statistics."""

    @staticmethod
    def calculate(formula: str, values: dict[str, float]) -> CalculationResult:
        """
        Safely calculate a KPI value from a formula and input values.

        Args:
            formula: The KPI formula string
            values: Dictionary of input field values

        Returns:
            CalculationResult with success status, value, and any error
        """
        try:
            # Convert all values to float, handle None
            clean_values = {}
            for key, val in values.items():
                if val is None:
                    return CalculationResult(
                        success=False,
                        value=None,
                        error=f"Missing value for field: {key}"
                    )
                try:
                    clean_values[key] = float(val)
                except (TypeError, ValueError):
                    return CalculationResult(
                        success=False,
                        value=None,
                        error=f"Invalid numeric value for field: {key}"
                    )

            # Calculate using formula parser
            result = FormulaParser.evaluate(formula, clean_values)

            # Check for infinity or NaN
            if result != result:  # NaN check
                return CalculationResult(
                    success=False,
                    value=None,
                    error="Calculation resulted in undefined value (NaN)"
                )
            if abs(result) == float('inf'):
                return CalculationResult(
                    success=False,
                    value=None,
                    error="Calculation resulted in infinity"
                )

            return CalculationResult(
                success=True,
                value=round(result, 4),  # Round to 4 decimal places
                error=None
            )

        except FormulaError as e:
            return CalculationResult(
                success=False,
                value=None,
                error=str(e)
            )
        except Exception as e:
            return CalculationResult(
                success=False,
                value=None,
                error=f"Calculation error: {str(e)}"
            )

    @staticmethod
    def calculate_stats(values: list[float], previous_period_values: Optional[list[float]] = None) -> StatsSummary:
        """
        Calculate statistical summary for a list of KPI values.

        Args:
            values: List of KPI values (most recent first)
            previous_period_values: Optional list of values from previous period for trend calculation

        Returns:
            StatsSummary with statistics and trend information
        """
        if not values:
            return StatsSummary(
                current_value=None,
                mean=None,
                median=None,
                std_dev=None,
                min_value=None,
                max_value=None,
                trend=None,
                trend_percentage=None,
                data_points=0
            )

        current_value = values[0] if values else None
        data_points = len(values)

        # Basic statistics
        mean = round(statistics.mean(values), 4) if values else None
        median = round(statistics.median(values), 4) if values else None
        min_value = round(min(values), 4) if values else None
        max_value = round(max(values), 4) if values else None

        # Standard deviation (requires at least 2 values)
        std_dev = None
        if len(values) >= 2:
            std_dev = round(statistics.stdev(values), 4)

        # Trend calculation
        trend = None
        trend_percentage = None

        if len(values) >= 2:
            # Compare recent vs older values within the period
            mid_point = len(values) // 2
            recent_avg = statistics.mean(values[:mid_point]) if mid_point > 0 else values[0]
            older_avg = statistics.mean(values[mid_point:])

            if older_avg != 0:
                trend_percentage = round(((recent_avg - older_avg) / abs(older_avg)) * 100, 2)

                if trend_percentage > 5:
                    trend = "up"
                elif trend_percentage < -5:
                    trend = "down"
                else:
                    trend = "stable"
            else:
                if recent_avg > 0:
                    trend = "up"
                    trend_percentage = 100.0
                elif recent_avg < 0:
                    trend = "down"
                    trend_percentage = -100.0
                else:
                    trend = "stable"
                    trend_percentage = 0.0

        return StatsSummary(
            current_value=current_value,
            mean=mean,
            median=median,
            std_dev=std_dev,
            min_value=min_value,
            max_value=max_value,
            trend=trend,
            trend_percentage=trend_percentage,
            data_points=data_points
        )

    @staticmethod
    def validate_input_values(
        required_fields: list[str],
        provided_values: dict[str, float]
    ) -> tuple[bool, list[str]]:
        """
        Validate that all required input fields have values.

        Args:
            required_fields: List of required field names
            provided_values: Dictionary of provided values

        Returns:
            Tuple of (is_valid, list of missing fields)
        """
        missing = [field for field in required_fields if field not in provided_values]
        return len(missing) == 0, missing
