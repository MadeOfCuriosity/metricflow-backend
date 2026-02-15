"""Custom exceptions and error handling for MetricFlow API."""

from fastapi import HTTPException, status


class MetricFlowException(HTTPException):
    """Base exception for MetricFlow API."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str | None = None,
    ):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


# Authentication Errors (401, 403)
class InvalidCredentialsError(MetricFlowException):
    """Raised when login credentials are invalid."""

    def __init__(self, detail: str = "Invalid email or password"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="INVALID_CREDENTIALS",
        )


class TokenExpiredError(MetricFlowException):
    """Raised when JWT token has expired."""

    def __init__(self, detail: str = "Token has expired"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="TOKEN_EXPIRED",
        )


class InvalidTokenError(MetricFlowException):
    """Raised when JWT token is invalid."""

    def __init__(self, detail: str = "Invalid token"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="INVALID_TOKEN",
        )


class ForbiddenError(MetricFlowException):
    """Raised when user lacks permission for an action."""

    def __init__(self, detail: str = "You do not have permission to perform this action"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="FORBIDDEN",
        )


# Resource Errors (404, 409)
class NotFoundError(MetricFlowException):
    """Raised when a resource is not found."""

    def __init__(self, resource: str = "Resource", detail: str | None = None):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail or f"{resource} not found",
            error_code="NOT_FOUND",
        )


class AlreadyExistsError(MetricFlowException):
    """Raised when trying to create a resource that already exists."""

    def __init__(self, resource: str = "Resource", detail: str | None = None):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail or f"{resource} already exists",
            error_code="ALREADY_EXISTS",
        )


# Validation Errors (400, 422)
class ValidationError(MetricFlowException):
    """Raised when input validation fails."""

    def __init__(self, detail: str = "Invalid input"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="VALIDATION_ERROR",
        )


class FormulaError(MetricFlowException):
    """Raised when a formula is invalid or cannot be evaluated."""

    def __init__(self, detail: str = "Invalid formula"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="FORMULA_ERROR",
        )


# Rate Limiting (429)
class RateLimitExceededError(MetricFlowException):
    """Raised when rate limit is exceeded."""

    def __init__(self, detail: str = "Rate limit exceeded. Please try again later."):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            error_code="RATE_LIMIT_EXCEEDED",
        )


# Server Errors (500, 503)
class InternalServerError(MetricFlowException):
    """Raised for unexpected server errors."""

    def __init__(self, detail: str = "An unexpected error occurred"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            error_code="INTERNAL_ERROR",
        )


class ServiceUnavailableError(MetricFlowException):
    """Raised when an external service is unavailable."""

    def __init__(self, service: str = "Service", detail: str | None = None):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail or f"{service} is temporarily unavailable",
            error_code="SERVICE_UNAVAILABLE",
        )
