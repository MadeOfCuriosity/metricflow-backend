"""Pytest configuration and fixtures."""

import os
import uuid

# Set test environment variables BEFORE importing app modules
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only-32chars")
os.environ.setdefault("ENVIRONMENT", "testing")

# Disable rate limiting for tests by monkey-patching BEFORE imports
from slowapi import Limiter
from slowapi.util import get_remote_address

# Create disabled limiters
_disabled_limiter = Limiter(key_func=get_remote_address, enabled=False)

# Patch the rate_limit module before it's imported elsewhere
import app.core.rate_limit as rate_limit_module
rate_limit_module.limiter = _disabled_limiter
rate_limit_module.public_limiter = _disabled_limiter

# Patch PostgreSQL types for SQLite compatibility BEFORE importing models
from sqlalchemy import String, TypeDecorator, JSON
import sqlalchemy.dialects.postgresql as pg_dialect


class SQLiteUUID(TypeDecorator):
    """Platform-independent UUID type that works with SQLite."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(uuid.UUID(value))
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(value)
        return value


# Monkey-patch the PostgreSQL UUID class before any models are imported
class MockUUID(SQLiteUUID):
    """Mock PostgreSQL UUID that works with SQLite for testing."""
    def __init__(self, as_uuid=True):
        super().__init__()
        self.as_uuid = as_uuid


class MockJSONB(TypeDecorator):
    """Mock PostgreSQL JSONB that works with SQLite for testing."""
    impl = JSON
    cache_ok = True

    def __init__(self, astext_type=None, none_as_null=False):
        super().__init__()


pg_dialect.UUID = MockUUID
pg_dialect.JSONB = MockJSONB

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.api.deps import get_db
from main import app

# Create in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with database override."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_org_data():
    """Sample organization registration data."""
    return {
        "org_name": "Test Company",
        "admin_email": "admin@test.com",
        "admin_password": "testpassword123",
        "admin_name": "Test Admin",
    }


@pytest.fixture
def test_user_credentials():
    """Sample user login credentials."""
    return {
        "email": "admin@test.com",
        "password": "testpassword123",
    }
