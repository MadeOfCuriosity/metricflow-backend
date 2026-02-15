from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4
import hashlib

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Token type constants
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"
TOKEN_TYPE_SETUP = "google_setup"

# Refresh token expiration (longer than access token)
REFRESH_TOKEN_EXPIRE_DAYS = 7


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def hash_token(token: str) -> str:
    """Create SHA-256 hash of a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    include_jti: bool = True,
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({
        "exp": expire,
        "type": TOKEN_TYPE_ACCESS,
    })

    # Add unique token ID for blacklisting
    if include_jti:
        to_encode["jti"] = str(uuid4())

    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(data: dict) -> tuple[str, datetime]:
    """
    Create a JWT refresh token.
    Returns (token, expires_at).
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({
        "exp": expire,
        "type": TOKEN_TYPE_REFRESH,
        "jti": str(uuid4()),
    })

    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt, expire


def verify_token(token: str, expected_type: Optional[str] = None) -> Optional[dict]:
    """
    Verify a JWT token and return the payload if valid.

    Args:
        token: The JWT token to verify
        expected_type: If provided, verify the token type matches
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )

        # Verify token type if specified
        if expected_type and payload.get("type") != expected_type:
            return None

        return payload
    except JWTError:
        return None


def is_token_blacklisted(db: Session, jti: str) -> bool:
    """Check if a token is blacklisted."""
    from app.models.token_blacklist import TokenBlacklist

    return db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first() is not None


def blacklist_token(
    db: Session,
    jti: str,
    user_id: str,
    token_type: str,
    expires_at: datetime,
) -> None:
    """Add a token to the blacklist."""
    from app.models.token_blacklist import TokenBlacklist

    blacklisted = TokenBlacklist(
        jti=jti,
        user_id=user_id,
        token_type=token_type,
        expires_at=expires_at,
    )
    db.add(blacklisted)
    db.commit()


def store_refresh_token(
    db: Session,
    user_id: str,
    token: str,
    expires_at: datetime,
) -> None:
    """Store a refresh token hash for rotation tracking."""
    from app.models.token_blacklist import RefreshToken

    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=expires_at,
    )
    db.add(refresh_token)
    db.commit()


def validate_refresh_token(db: Session, token: str) -> bool:
    """Validate that a refresh token is still valid (not revoked)."""
    from app.models.token_blacklist import RefreshToken

    token_hash = hash_token(token)
    refresh = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.utcnow(),
    ).first()

    return refresh is not None


def rotate_refresh_token(
    db: Session,
    old_token: str,
    user_id: str,
) -> tuple[str, datetime]:
    """
    Rotate a refresh token - invalidate old one and create new one.
    Returns (new_token, expires_at).
    """
    from app.models.token_blacklist import RefreshToken

    # Mark old token as rotated
    old_hash = hash_token(old_token)
    db.query(RefreshToken).filter(
        RefreshToken.token_hash == old_hash
    ).update({
        "is_revoked": True,
        "rotated_at": datetime.utcnow(),
    })

    # Create new refresh token
    new_token, expires_at = create_refresh_token({"sub": user_id})

    # Store new token
    store_refresh_token(db, user_id, new_token, expires_at)

    db.commit()
    return new_token, expires_at


def revoke_all_user_tokens(db: Session, user_id: str) -> None:
    """Revoke all refresh tokens for a user (e.g., on password change)."""
    from app.models.token_blacklist import RefreshToken

    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.is_revoked == False,
    ).update({"is_revoked": True})
    db.commit()


def verify_google_id_token(credential: str, client_id: str) -> Optional[dict]:
    """
    Verify a Google ID token and return the payload.
    Returns dict with: sub, email, name, picture, email_verified.
    Returns None if verification fails.
    """
    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id,
        )
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            return None
        if not idinfo.get('email_verified', False):
            return None
        return idinfo
    except ValueError:
        return None


def create_google_setup_token(google_data: dict) -> str:
    """
    Create a short-lived JWT that embeds verified Google user info.
    Used between the initial Google auth and org setup completion.
    """
    to_encode = {
        "google_sub": google_data["sub"],
        "email": google_data["email"],
        "name": google_data.get("name", ""),
        "type": TOKEN_TYPE_SETUP,
        "exp": datetime.utcnow() + timedelta(minutes=settings.GOOGLE_SETUP_TOKEN_EXPIRE_MINUTES),
        "jti": str(uuid4()),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def cleanup_expired_tokens(db: Session) -> int:
    """
    Remove expired tokens from blacklist.
    Returns number of tokens removed.
    """
    from app.models.token_blacklist import TokenBlacklist, RefreshToken

    now = datetime.utcnow()

    # Clean blacklist
    blacklist_deleted = db.query(TokenBlacklist).filter(
        TokenBlacklist.expires_at < now
    ).delete()

    # Clean expired refresh tokens
    refresh_deleted = db.query(RefreshToken).filter(
        RefreshToken.expires_at < now
    ).delete()

    db.commit()
    return blacklist_deleted + refresh_deleted
