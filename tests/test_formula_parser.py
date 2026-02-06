"""Tests for formula parser utility."""

import pytest
from app.core.formula_parser import FormulaParser, FormulaError, validate_formula


class TestFormulaParser:
    """Test safe formula parsing and evaluation."""

    @pytest.fixture
    def parser(self):
        """Create a formula parser instance."""
        return FormulaParser()

    def test_simple_addition(self, parser):
        """Test basic addition."""
        result = parser.evaluate("a + b", {"a": 5, "b": 3})
        assert result == 8

    def test_simple_subtraction(self, parser):
        """Test basic subtraction."""
        result = parser.evaluate("a - b", {"a": 10, "b": 3})
        assert result == 7

    def test_multiplication(self, parser):
        """Test multiplication."""
        result = parser.evaluate("a * b", {"a": 4, "b": 5})
        assert result == 20

    def test_division(self, parser):
        """Test division."""
        result = parser.evaluate("a / b", {"a": 20, "b": 4})
        assert result == 5

    def test_complex_formula(self, parser):
        """Test complex formula with multiple operations."""
        result = parser.evaluate(
            "(conversions / visitors) * 100",
            {"conversions": 50, "visitors": 1000},
        )
        assert result == 5.0

    def test_parentheses(self, parser):
        """Test formula with parentheses."""
        result = parser.evaluate("(a + b) * c", {"a": 2, "b": 3, "c": 4})
        assert result == 20

    def test_negative_numbers(self, parser):
        """Test handling negative numbers."""
        result = parser.evaluate("a + b", {"a": -5, "b": 10})
        assert result == 5

    def test_decimal_numbers(self, parser):
        """Test decimal number handling."""
        result = parser.evaluate("a * b", {"a": 2.5, "b": 4})
        assert result == 10.0

    def test_division_by_zero(self, parser):
        """Test that division by zero raises an error."""
        with pytest.raises(FormulaError):
            parser.evaluate("a / b", {"a": 10, "b": 0})

    def test_missing_variable(self, parser):
        """Test formula with missing variable."""
        with pytest.raises(FormulaError):
            parser.evaluate("a + b + c", {"a": 1, "b": 2})

    def test_extract_variables(self, parser):
        """Test extracting variables from formula."""
        variables = parser.extract_variables("(conversions / visitors) * 100")
        assert "conversions" in variables
        assert "visitors" in variables

    def test_validate_formula_valid(self, parser):
        """Test formula validation with valid formula."""
        is_valid, error, variables = parser.validate_formula("(a + b) / c")
        assert is_valid is True
        assert error == ""
        assert "a" in variables
        assert "b" in variables
        assert "c" in variables

    def test_validate_formula_invalid(self, parser):
        """Test formula validation with invalid formula."""
        # Use a truly invalid formula (unclosed parenthesis)
        is_valid, error, variables = parser.validate_formula("(a + b")
        assert is_valid is False
        assert error != ""

    def test_dangerous_code_blocked(self, parser):
        """Test that dangerous code is blocked."""
        # These should all fail or be blocked
        dangerous_formulas = [
            "__import__('os').system('ls')",
            "eval('1+1')",
            "exec('print(1)')",
            "open('/etc/passwd').read()",
        ]

        for formula in dangerous_formulas:
            with pytest.raises(Exception):
                parser.evaluate(formula, {})

    def test_single_variable(self, parser):
        """Test formula with single variable."""
        result = parser.evaluate("value", {"value": 42})
        assert result == 42

    def test_numeric_constant(self, parser):
        """Test formula with numeric constant."""
        result = parser.evaluate("a * 100", {"a": 0.5})
        assert result == 50

    def test_validate_formula_function(self):
        """Test the standalone validate_formula function."""
        is_valid, error, variables = validate_formula("revenue / total_users")
        assert is_valid is True
        assert "revenue" in variables
        assert "total_users" in variables
