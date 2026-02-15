"""Rate limiting configuration using slowapi."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
from typing import Optional


def get_user_identifier(request: Request) -> str:
    """
    Get identifier for rate limiting.
    Uses user ID if authenticated, otherwise IP address.
    """
    # Check for user in request state (set by auth middleware)
    user = getattr(request.state, "user", None)
    if user and hasattr(user, "id"):
        return f"user:{user.id}"

    # Fall back to IP address
    return get_remote_address(request)


def get_ip_address(request: Request) -> str:
    """Get IP address for rate limiting public routes."""
    return get_remote_address(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_user_identifier,
    default_limits=["1000/minute"],  # Default for authenticated users
)

# Separate limiter for public routes (stricter)
public_limiter = Limiter(
    key_func=get_ip_address,
    default_limits=["100/minute"],
)


# Rate limit decorators for different use cases
def rate_limit_public(limit: str = "100/minute"):
    """Rate limit for public routes (by IP)."""
    return public_limiter.limit(limit)


def rate_limit_auth(limit: str = "1000/minute"):
    """Rate limit for authenticated routes (by user)."""
    return limiter.limit(limit)


def rate_limit_sensitive(limit: str = "10/minute"):
    """Rate limit for sensitive operations (login, register)."""
    return public_limiter.limit(limit)


def rate_limit_ai(limit: str = "20/hour"):
    """Rate limit for AI endpoints (expensive operations)."""
    return limiter.limit(limit)
