"""Security middleware for MetricFlow API."""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Enable XSS filter in browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy (adjust as needed)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

        # Permissions Policy (formerly Feature Policy)
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), "
            "camera=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "magnetometer=(), "
            "microphone=(), "
            "payment=(), "
            "usb=()"
        )

        # Strict Transport Security (HSTS) - only in production
        # Uncomment when using HTTPS
        # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Cache control for API responses
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        return response


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Validate incoming requests for security."""

    # Maximum request body size (10MB)
    MAX_BODY_SIZE = 10 * 1024 * 1024

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check content length
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_BODY_SIZE:
            return Response(
                content='{"detail": "Request body too large"}',
                status_code=413,
                media_type="application/json",
            )

        # Validate content type for POST/PUT/PATCH
        if request.method in ("POST", "PUT", "PATCH"):
            content_type = request.headers.get("content-type", "")
            allowed_types = [
                "application/json",
                "application/x-www-form-urlencoded",
                "multipart/form-data",
            ]
            if content_type and not any(t in content_type for t in allowed_types):
                return Response(
                    content='{"detail": "Unsupported content type"}',
                    status_code=415,
                    media_type="application/json",
                )

        return await call_next(request)


class SQLInjectionPreventionMiddleware(BaseHTTPMiddleware):
    """
    Additional layer of SQL injection prevention.
    Note: SQLAlchemy ORM already prevents SQL injection when used correctly.
    This is a defense-in-depth measure for query parameters only.
    """

    # Only match clear SQL injection patterns (multi-word to avoid false positives)
    SQL_PATTERNS = [
        "' OR '1'='1",
        "'; DROP TABLE",
        "'; DELETE FROM",
        "UNION SELECT",
        "UNION ALL SELECT",
        "EXEC(",
        "EXECUTE(",
    ]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check query parameters
        query_string = str(request.query_params).upper()
        for pattern in self.SQL_PATTERNS:
            if pattern in query_string:
                return Response(
                    content='{"detail": "Invalid request parameters"}',
                    status_code=400,
                    media_type="application/json",
                )

        return await call_next(request)
