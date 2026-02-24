from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import logging
import os

from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import MetricFlowException
from app.core.rate_limit import limiter, public_limiter
from app.core.middleware import (
    SecurityHeadersMiddleware,
    RequestValidationMiddleware,
    SQLInjectionPreventionMiddleware,
)
from app.api.routes.auth import router as auth_router
from app.api.routes.kpis import router as kpis_router
from app.api.routes.entries import router as entries_router
from app.api.routes.insights import router as insights_router
from app.api.routes.ai import router as ai_router
from app.api.routes.rooms import router as rooms_router
from app.api.routes.users import router as users_router
from app.api.routes.data_fields import router as data_fields_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.admin import router as admin_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_migrations():
    """Run database migrations on startup."""
    try:
        from alembic.config import Config
        from alembic import command

        logger.info("Running database migrations...")
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Failed to run migrations: {e}")
        # Don't fail startup, migrations might already be applied
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting MetricFlow API...")

    # Validate required secrets (warn but don't crash — App Runner rolls back config on failure)
    config_errors = settings.validate_required_secrets()
    if config_errors:
        for err in config_errors:
            logger.warning(f"Configuration warning: {err}")

    # Run migrations in production
    if IS_PRODUCTION:
        run_migrations()

    # Start integration sync scheduler
    from app.core.scheduler import start_scheduler, shutdown_scheduler
    start_scheduler()

    logger.info("MetricFlow API started successfully")
    yield
    # Shutdown
    shutdown_scheduler()
    logger.info("Shutting down MetricFlow API...")

# Determine if running in production
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development") == "production"

app = FastAPI(
    title="MetricFlow API",
    description="Business KPI tracking SaaS application",
    version="1.0.0",
    lifespan=lifespan,
    # Disable docs in production
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Exception handlers
@app.exception_handler(MetricFlowException)
async def metricflow_exception_handler(request: Request, exc: MetricFlowException):
    """Handle custom MetricFlow exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "error_code": exc.error_code,
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    """Handle database errors."""
    logger.error(f"Database error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "A database error occurred",
            "error_code": "DATABASE_ERROR",
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred",
            "error_code": "INTERNAL_ERROR",
        },
    )

# Security middleware (order matters - first added = last executed)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestValidationMiddleware)
app.add_middleware(SQLInjectionPreventionMiddleware)

# Configure CORS with tightened settings
allowed_origins = [settings.FRONTEND_URL]
if not IS_PRODUCTION:
    # Allow localhost variations in development
    allowed_origins.extend([
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Origin",
        "X-Requested-With",
    ],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    max_age=600,  # Cache preflight requests for 10 minutes
)

# Include routers
app.include_router(auth_router, prefix="/api")
app.include_router(kpis_router, prefix="/api")
app.include_router(entries_router, prefix="/api")
app.include_router(insights_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(rooms_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(data_fields_router, prefix="/api")
app.include_router(integrations_router, prefix="/api")
app.include_router(admin_router, prefix="/api")


@app.get("/")
def root():
    return {"message": "Welcome to MetricFlow API"}


@app.get("/health")
def health_check():
    """Health check endpoint for load balancers and monitoring."""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
    }

    # Check database connectivity
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        health_status["database"] = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status["status"] = "unhealthy"
        health_status["database"] = "disconnected"

    return health_status
