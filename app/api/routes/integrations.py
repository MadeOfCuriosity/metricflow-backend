import logging
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin_org
from app.core.config import settings
from app.models import User, Organization
from app.schemas.integrations import (
    CreateIntegrationRequest,
    UpdateIntegrationRequest,
    SetFieldMappingsRequest,
    IntegrationListResponse,
    IntegrationResponse,
    IntegrationDetailResponse,
    FieldMappingListResponse,
    ExternalFieldListResponse,
    ExternalFieldResponse,
    SyncLogListResponse,
    SyncLogResponse,
    OAuthAuthorizeResponse,
)
from app.services.integration_service import IntegrationService
from app.services.sync_service import SyncService
from app.services.connectors import get_connector
from app.services.connectors.google_sheets import GoogleSheetsConnector
from app.services.connectors.zoho_crm import ZohoCRMConnector
from app.services.connectors.zoho_books import ZohoBooksConnector
from app.services.connectors.zoho_sheet import ZohoSheetConnector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["Integrations"])


# --- CRUD ---

@router.get("", response_model=IntegrationListResponse)
def list_integrations(
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """List all integrations for the organization."""
    user, org = admin_org
    integrations = IntegrationService.get_all(db, org.id)
    return IntegrationListResponse(
        integrations=[IntegrationService.to_response(i) for i in integrations],
        total=len(integrations),
    )


@router.post("", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED)
def create_integration(
    data: CreateIntegrationRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Create a new integration."""
    user, org = admin_org
    integration = IntegrationService.create(db, org.id, user.id, data)

    # If LeadSquared, test connection immediately
    if data.provider == "leadsquared" and data.api_key:
        try:
            connector = get_connector(integration, db)
            if not connector.test_connection():
                IntegrationService.set_error(db, integration, "Connection test failed. Check API keys.")
        except Exception as e:
            IntegrationService.set_error(db, integration, str(e))

    # Set up scheduled sync if not manual
    if integration.sync_schedule != "manual" and integration.status == "connected":
        from app.core.scheduler import scheduler
        SyncService.add_sync_job(scheduler, integration)

    return IntegrationService.to_response(integration)


@router.get("/{integration_id}", response_model=IntegrationDetailResponse)
def get_integration(
    integration_id: UUID,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Get integration details with mappings and recent logs."""
    user, org = admin_org
    integration = IntegrationService.get_by_id(db, integration_id, org.id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    mappings = IntegrationService.get_mappings(db, integration.id)
    logs = IntegrationService.get_sync_logs(db, integration.id, limit=10)

    resp = IntegrationService.to_response(integration)
    return IntegrationDetailResponse(
        **resp.model_dump(),
        field_mappings=[IntegrationService.mapping_to_response(m) for m in mappings],
        recent_logs=[SyncLogResponse.model_validate(log) for log in logs],
    )


@router.put("/{integration_id}", response_model=IntegrationResponse)
def update_integration(
    integration_id: UUID,
    data: UpdateIntegrationRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Update integration config or schedule."""
    user, org = admin_org
    integration = IntegrationService.get_by_id(db, integration_id, org.id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    old_schedule = integration.sync_schedule
    integration = IntegrationService.update(db, integration, data)

    # Update scheduler if schedule changed
    if data.sync_schedule and data.sync_schedule != old_schedule:
        from app.core.scheduler import scheduler
        if data.sync_schedule == "manual":
            SyncService.remove_sync_job(scheduler, integration.id)
        elif integration.status == "connected":
            SyncService.add_sync_job(scheduler, integration)

    return IntegrationService.to_response(integration)


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration(
    integration_id: UUID,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Disconnect and delete an integration."""
    user, org = admin_org
    integration = IntegrationService.get_by_id(db, integration_id, org.id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    # Remove scheduled job
    from app.core.scheduler import scheduler
    SyncService.remove_sync_job(scheduler, integration.id)

    IntegrationService.delete(db, integration)


# --- Sync ---

@router.post("/{integration_id}/sync", response_model=SyncLogResponse)
def trigger_sync(
    integration_id: UUID,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Manually trigger a data sync."""
    user, org = admin_org
    integration = IntegrationService.get_by_id(db, integration_id, org.id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    if integration.status not in ("connected", "error"):
        raise HTTPException(
            status_code=400,
            detail="Integration must be connected before syncing. Complete the setup first.",
        )

    sync_log = SyncService.execute_sync(
        db, integration.id,
        triggered_by=user.id,
        trigger_type="manual",
    )
    return SyncLogResponse.model_validate(sync_log)


@router.get("/{integration_id}/logs", response_model=SyncLogListResponse)
def get_sync_logs(
    integration_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Get sync history for an integration."""
    user, org = admin_org
    integration = IntegrationService.get_by_id(db, integration_id, org.id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    logs = IntegrationService.get_sync_logs(db, integration.id, limit)
    return SyncLogListResponse(
        logs=[SyncLogResponse.model_validate(log) for log in logs],
        total=len(logs),
    )


# --- External Fields ---

@router.get("/{integration_id}/external-fields", response_model=ExternalFieldListResponse)
def get_external_fields(
    integration_id: UUID,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Fetch available fields from the external data source."""
    user, org = admin_org
    integration = IntegrationService.get_by_id(db, integration_id, org.id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    if integration.status not in ("connected", "error"):
        raise HTTPException(
            status_code=400,
            detail="Integration must be connected to fetch fields.",
        )

    try:
        connector = get_connector(integration, db)
        fields = connector.get_available_fields()
        return ExternalFieldListResponse(
            fields=[ExternalFieldResponse(name=f.name, label=f.label, field_type=f.field_type) for f in fields],
            total=len(fields),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch fields: {str(e)}")


# --- Field Mappings ---

@router.post("/{integration_id}/mappings", response_model=FieldMappingListResponse)
def set_field_mappings(
    integration_id: UUID,
    data: SetFieldMappingsRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Set field mappings for an integration (replaces existing)."""
    user, org = admin_org
    integration = IntegrationService.get_by_id(db, integration_id, org.id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    mappings = IntegrationService.set_mappings(db, integration.id, data.mappings)
    return FieldMappingListResponse(
        mappings=[IntegrationService.mapping_to_response(m) for m in mappings],
        total=len(mappings),
    )


# --- OAuth ---

@router.get("/oauth/{provider}/authorize", response_model=OAuthAuthorizeResponse)
def get_oauth_authorize_url(
    provider: str,
    integration_id: UUID = Query(...),
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Generate OAuth authorization URL."""
    user, org = admin_org

    if provider not in ("google_sheets", "zoho_crm", "zoho_books", "zoho_sheet"):
        raise HTTPException(status_code=400, detail="OAuth not supported for this provider")

    integration = IntegrationService.get_by_id(db, integration_id, org.id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    state = IntegrationService.generate_oauth_state(integration.id)

    if provider == "google_sheets":
        if not settings.GOOGLE_OAUTH_CLIENT_ID:
            raise HTTPException(status_code=500, detail="Google OAuth not configured")
        authorize_url = GoogleSheetsConnector.get_authorize_url(state)
    elif provider == "zoho_crm":
        if not settings.ZOHO_OAUTH_CLIENT_ID:
            raise HTTPException(status_code=500, detail="Zoho OAuth not configured")
        authorize_url = ZohoCRMConnector.get_authorize_url(state)
    elif provider == "zoho_books":
        if not settings.ZOHO_OAUTH_CLIENT_ID:
            raise HTTPException(status_code=500, detail="Zoho OAuth not configured")
        authorize_url = ZohoBooksConnector.get_authorize_url(state)
    elif provider == "zoho_sheet":
        if not settings.ZOHO_OAUTH_CLIENT_ID:
            raise HTTPException(status_code=500, detail="Zoho OAuth not configured")
        authorize_url = ZohoSheetConnector.get_authorize_url(state)
    else:
        raise HTTPException(status_code=400, detail="Unknown provider")

    return OAuthAuthorizeResponse(authorize_url=authorize_url, state=state)


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle OAuth callback from provider."""
    integration_id, csrf_token = IntegrationService.parse_oauth_state(state)
    if not integration_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    from app.models.integration import Integration as IntegrationModel
    integration = db.query(IntegrationModel).filter(
        IntegrationModel.id == integration_id,
    ).first()

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    try:
        if provider == "google_sheets":
            tokens = GoogleSheetsConnector.exchange_code(code)
        elif provider == "zoho_crm":
            tokens = ZohoCRMConnector.exchange_code(code)
        elif provider == "zoho_books":
            tokens = ZohoBooksConnector.exchange_code(code)
        elif provider == "zoho_sheet":
            tokens = ZohoSheetConnector.exchange_code(code)
        else:
            raise HTTPException(status_code=400, detail="Unknown provider")

        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        IntegrationService.update_oauth_tokens(
            db, integration, access_token, refresh_token, expires_at
        )

        # Redirect back to frontend
        redirect_url = f"{settings.FRONTEND_URL}/integrations?connected={provider}&id={integration.id}"
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        logger.error(f"OAuth callback failed for {provider}: {e}")
        IntegrationService.set_error(db, integration, f"OAuth failed: {str(e)}")
        redirect_url = f"{settings.FRONTEND_URL}/integrations?error=oauth_failed&provider={provider}"
        return RedirectResponse(url=redirect_url)
