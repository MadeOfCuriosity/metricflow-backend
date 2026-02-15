"""
Safe formula parser for KPI calculations.
Supports basic arithmetic operations without using eval().
"""
import ast
import operator
import re
from typing import Any


# Supported operators
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
}

# Pattern to extract variable names from formula
VARIABLE_PATTERN = re.compile(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b')

# Reserved keywords that shouldn't be treated as variables
RESERVED_KEYWORDS = {'True', 'False', 'None', 'and', 'or', 'not'}


class FormulaError(Exception):
    """Exception raised for formula parsing/evaluation errors."""
    pass


class FormulaParser:
    """
    Safe formula parser that validates and evaluates mathematical expressions.

    Supports:
    - Basic arithmetic: +, -, *, /, **, %
    - Parentheses for grouping
    - Variable names (snake_case identifiers)
    - Numeric literals (int and float)

    Does NOT support:
    - Function calls (no eval, exec, etc.)
    - Attribute access
    - Subscript operations
    - Any Python builtins
    """

    @staticmethod
    def extract_variables(formula: str) -> list[str]:
        """
        Extract all variable names from a formula string.

        Args:
            formula: The formula string (e.g., "revenue / deals_closed")

        Returns:
            List of unique variable names found in the formula
        """
        matches = VARIABLE_PATTERN.findall(formula)
        # Filter out reserved keywords and duplicates
        variables = list(dict.fromkeys(
            var for var in matches
            if var not in RESERVED_KEYWORDS
        ))
        return variables

    @staticmethod
    def validate_formula(formula: str) -> tuple[bool, str, list[str]]:
        """
        Validate a formula string for syntax and safety.

        Args:
            formula: The formula string to validate

        Returns:
            Tuple of (is_valid, error_message, input_fields)
            - is_valid: True if formula is valid
            - error_message: Empty string if valid, error description if not
            - input_fields: List of required input field names
        """
        if not formula or not formula.strip():
            return False, "Formula cannot be empty", []

        # Extract variables first
        variables = FormulaParser.extract_variables(formula)

        if not variables:
            return False, "Formula must contain at least one variable", []

        try:
            # Parse the formula into an AST
            tree = ast.parse(formula, mode='eval')

            # Validate the AST structure
            FormulaParser._validate_ast(tree.body)

            return True, "", variables

        except SyntaxError as e:
            return False, f"Syntax error: {str(e)}", []
        except FormulaError as e:
            return False, str(e), []
        except Exception as e:
            return False, f"Invalid formula: {str(e)}", []

    @staticmethod
    def _validate_ast(node: ast.AST) -> None:
        """
        Recursively validate AST nodes to ensure only safe operations.

        Raises:
            FormulaError: If an unsafe operation is detected
        """
        if isinstance(node, ast.Expression):
            FormulaParser._validate_ast(node.body)

        elif isinstance(node, ast.BinOp):
            # Binary operations: +, -, *, /, **, %
            if type(node.op) not in OPERATORS:
                raise FormulaError(f"Unsupported operator: {type(node.op).__name__}")
            FormulaParser._validate_ast(node.left)
            FormulaParser._validate_ast(node.right)

        elif isinstance(node, ast.UnaryOp):
            # Unary operations: +, -
            if type(node.op) not in OPERATORS:
                raise FormulaError(f"Unsupported unary operator: {type(node.op).__name__}")
            FormulaParser._validate_ast(node.operand)

        elif isinstance(node, ast.Constant):
            # Numeric literals (Python 3.8+)
            if not isinstance(node.value, (int, float)):
                raise FormulaError(f"Only numeric constants are allowed, got: {type(node.value).__name__}")

        elif isinstance(node, ast.Name):
            # Variable names
            if node.id in RESERVED_KEYWORDS:
                raise FormulaError(f"Reserved keyword cannot be used as variable: {node.id}")

        elif isinstance(node, ast.Call):
            raise FormulaError("Function calls are not allowed in formulas")

        elif isinstance(node, ast.Attribute):
            raise FormulaError("Attribute access is not allowed in formulas")

        elif isinstance(node, ast.Subscript):
            raise FormulaError("Subscript operations are not allowed in formulas")

        else:
            raise FormulaError(f"Unsupported expression type: {type(node).__name__}")

    @staticmethod
    def evaluate(formula: str, values: dict[str, float]) -> float:
        """
        Safely evaluate a formula with given variable values.

        Args:
            formula: The formula string
            values: Dictionary mapping variable names to their values

        Returns:
            The calculated result

        Raises:
            FormulaError: If evaluation fails
        """
        # Validate formula first
        is_valid, error, variables = FormulaParser.validate_formula(formula)
        if not is_valid:
            raise FormulaError(error)

        # Check all required variables are provided
        missing = set(variables) - set(values.keys())
        if missing:
            raise FormulaError(f"Missing values for variables: {', '.join(missing)}")

        try:
            tree = ast.parse(formula, mode='eval')
            result = FormulaParser._evaluate_ast(tree.body, values)

            if not isinstance(result, (int, float)):
                raise FormulaError(f"Formula must evaluate to a number, got: {type(result).__name__}")

            return float(result)

        except ZeroDivisionError:
            raise FormulaError("Division by zero")
        except FormulaError:
            raise
        except Exception as e:
            raise FormulaError(f"Evaluation error: {str(e)}")

    @staticmethod
    def _evaluate_ast(node: ast.AST, values: dict[str, float]) -> float:
        """
        Recursively evaluate AST nodes with given variable values.
        """
        if isinstance(node, ast.Expression):
            return FormulaParser._evaluate_ast(node.body, values)

        elif isinstance(node, ast.BinOp):
            left = FormulaParser._evaluate_ast(node.left, values)
            right = FormulaParser._evaluate_ast(node.right, values)
            op_func = OPERATORS[type(node.op)]
            return op_func(left, right)

        elif isinstance(node, ast.UnaryOp):
            operand = FormulaParser._evaluate_ast(node.operand, values)
            op_func = OPERATORS[type(node.op)]
            return op_func(operand)

        elif isinstance(node, ast.Constant):
            # Numeric literals (Python 3.8+)
            return node.value

        elif isinstance(node, ast.Name):
            return values[node.id]

        else:
            raise FormulaError(f"Cannot evaluate: {type(node).__name__}")


# Convenience functions
def validate_formula(formula: str) -> tuple[bool, str, list[str]]:
    """Validate a formula string."""
    return FormulaParser.validate_formula(formula)


def evaluate_formula(formula: str, values: dict[str, float]) -> float:
    """Evaluate a formula with given values."""
    return FormulaParser.evaluate(formula, values)


def extract_input_fields(formula: str) -> list[str]:
    """Extract input field names from a formula."""
    return FormulaParser.extract_variables(formula)
