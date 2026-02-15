from app.api.routes.auth import router as auth_router
from app.api.routes.kpis import router as kpis_router
from app.api.routes.entries import router as entries_router
from app.api.routes.insights import router as insights_router
from app.api.routes.ai import router as ai_router

__all__ = ["auth_router", "kpis_router", "entries_router", "insights_router", "ai_router"]
