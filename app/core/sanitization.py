"""Input sanitization and validation utilities."""

import re
import html
from typing import Optional
import bleach


# Maximum lengths for different field types
MAX_LENGTHS = {
    "name": 100,
    "email": 255,
    "password": 128,
    "description": 1000,
    "formula": 500,
    "message": 5000,
    "slug": 50,
    "default": 255,
}

# Allowed characters patterns
PATTERNS = {
    "slug": re.compile(r"^[a-z0-9-]+$"),
    "email": re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"),
    "name": re.compile(r"^[a-zA-Z0-9\s\-_.']+$"),
    "formula_var": re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$"),
}

# Dangerous patterns to detect in formulas
DANGEROUS_FORMULA_PATTERNS = [
    r"__\w+__",  # Dunder methods
    r"\bimport\b",
    r"\beval\b",
    r"\bexec\b",
    r"\bcompile\b",
    r"\bopen\b",
    r"\bfile\b",
    r"\binput\b",
    r"\bgetattr\b",
    r"\bsetattr\b",
    r"\bdelattr\b",
    r"\bglobals\b",
    r"\blocals\b",
    r"\bvars\b",
    r"\bdir\b",
    r"\btype\b",
    r"\bbreakpoint\b",
    r"\bos\.",
    r"\bsys\.",
    r"\bsubprocess\b",
]


def sanitize_string(
    value: str,
    max_length: int = MAX_LENGTHS["default"],
    strip_html: bool = True,
    allow_newlines: bool = False,
) -> str:
    """
    Sanitize a string input.

    - Strips leading/trailing whitespace
    - Removes or escapes HTML
    - Truncates to max length
    - Optionally removes newlines
    """
    if not value:
        return ""

    # Strip whitespace
    value = value.strip()

    # Remove HTML tags if requested
    if strip_html:
        value = bleach.clean(value, tags=[], strip=True)

    # Remove or normalize newlines
    if not allow_newlines:
        value = " ".join(value.split())

    # Truncate to max length
    if len(value) > max_length:
        value = value[:max_length]

    return value


def sanitize_name(value: str) -> str:
    """Sanitize a name field (person name, org name, KPI name)."""
    return sanitize_string(value, max_length=MAX_LENGTHS["name"])


def sanitize_email(value: str) -> str:
    """Sanitize and validate email."""
    value = sanitize_string(value, max_length=MAX_LENGTHS["email"]).lower()
    return value


def validate_email(value: str) -> bool:
    """Validate email format."""
    if not value or len(value) > MAX_LENGTHS["email"]:
        return False
    return bool(PATTERNS["email"].match(value))


def sanitize_description(value: str) -> str:
    """Sanitize a description field (allows newlines)."""
    return sanitize_string(
        value,
        max_length=MAX_LENGTHS["description"],
        allow_newlines=True,
    )


def sanitize_slug(value: str) -> str:
    """Sanitize a URL slug."""
    value = sanitize_string(value, max_length=MAX_LENGTHS["slug"])
    # Convert to lowercase and replace spaces with hyphens
    value = value.lower().replace(" ", "-")
    # Remove invalid characters
    value = re.sub(r"[^a-z0-9-]", "", value)
    # Remove multiple consecutive hyphens
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def validate_slug(value: str) -> bool:
    """Validate slug format."""
    if not value or len(value) > MAX_LENGTHS["slug"]:
        return False
    return bool(PATTERNS["slug"].match(value))


def sanitize_formula(value: str) -> str:
    """
    Sanitize a formula string.
    Removes potentially dangerous code patterns.
    """
    value = sanitize_string(value, max_length=MAX_LENGTHS["formula"])

    # Check for dangerous patterns
    for pattern in DANGEROUS_FORMULA_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            raise ValueError(f"Formula contains disallowed pattern")

    return value


def validate_formula(value: str) -> tuple[bool, Optional[str]]:
    """
    Validate a formula string.
    Returns (is_valid, error_message).
    """
    if not value:
        return False, "Formula cannot be empty"

    if len(value) > MAX_LENGTHS["formula"]:
        return False, f"Formula exceeds maximum length of {MAX_LENGTHS['formula']}"

    # Check for dangerous patterns
    for pattern in DANGEROUS_FORMULA_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            return False, "Formula contains disallowed pattern"

    # Only allow safe characters
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+-*/()., ")
    if not all(c in allowed_chars for c in value):
        return False, "Formula contains invalid characters"

    # Check balanced parentheses
    if value.count("(") != value.count(")"):
        return False, "Formula has unbalanced parentheses"

    return True, None


def validate_input_fields(fields: list[str]) -> tuple[bool, Optional[str]]:
    """
    Validate input field names.
    Returns (is_valid, error_message).
    """
    if not fields:
        return False, "At least one input field is required"

    if len(fields) > 20:
        return False, "Maximum 20 input fields allowed"

    for field in fields:
        if not field:
            return False, "Field name cannot be empty"
        if len(field) > 50:
            return False, f"Field name '{field}' exceeds maximum length"
        if not PATTERNS["formula_var"].match(field):
            return False, f"Field name '{field}' contains invalid characters"

    return True, None


def sanitize_message(value: str) -> str:
    """Sanitize a chat/AI message."""
    return sanitize_string(
        value,
        max_length=MAX_LENGTHS["message"],
        allow_newlines=True,
    )


def escape_for_display(value: str) -> str:
    """Escape a string for safe display in HTML context."""
    return html.escape(value)
