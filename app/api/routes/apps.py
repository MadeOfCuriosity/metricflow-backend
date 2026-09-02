import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin_org
from app.models import User, Organization
from app.models.app_run_record import AppRunRecord
from app.schemas.apps import (
    AppListResponse,
    AppSummaryResponse,
    AppConfigFieldResponse,
    AppInstallationResponse,
    ConfigureAppRequest,
    SetSecretConfigRequest,
    RunAppRequest,
    AppRunRecordResponse,
    AppRunRecordListResponse,
)
from app.services.apps import list_apps
from app.services.apps.base import TRIGGER_ON_DEMAND
from app.services.app_installation_service import AppInstallationService, AppInstallationError
from app.services.app_runner import AppRunner
from app.services.app_secret_config import set_secret_config, secret_config_status, SecretConfigError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apps", tags=["Apps"])


def _config_schema_response(app) -> list[AppConfigFieldResponse]:
    return [
        AppConfigFieldResponse(
            key=f.key, label=f.label, field_type=f.field_type, required=f.required,
            secret=f.secret, options=f.options, default=f.default, help_text=f.help_text,
        )
        for f in app.config_schema
    ]


def _installation_response(installation) -> AppInstallationResponse:
    """Never model_validate an installation without also attaching its
    masked secret-config status — this is the one place that response is
    assembled, so a missing status can't slip through on some code path."""
    resp = AppInstallationResponse.model_validate(installation)
    resp.secret_config_status = secret_config_status(installation)
    return resp


@router.get("", response_model=AppListResponse)
def list_available_apps(
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """List every registered app with this org's installation state, if any."""
    _, org = admin_org
    installations = {
        i.app_key: i for i in AppInstallationService.get_all(db, org.id)
    }

    summaries = []
    for app in list_apps():
        if app.dev_only:
            continue
        installation = installations.get(app.key)
        summaries.append(AppSummaryResponse(
            key=app.key,
            name=app.name,
            description=app.description,
            requires_entitlement=app.requires_entitlement,
            triggers=app.triggers,
            default_schedule=app.default_schedule,
            config_schema=_config_schema_response(app),
            installation=_installation_response(installation) if installation else None,
        ))

    return AppListResponse(apps=summaries)


def _get_installation_or_404(db: Session, org_id: uuid.UUID, app_key: str):
    installation = AppInstallationService.get_by_key(db, org_id, app_key)
    if installation is None:
        raise HTTPException(status_code=404, detail=f"{app_key} is not installed")
    return installation


@router.post("/{app_key}/install", response_model=AppInstallationResponse, status_code=status.HTTP_201_CREATED)
def install_app(
    app_key: str,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    user, org = admin_org
    try:
        installation = AppInstallationService.install(db, org.id, app_key, user.id)
    except AppInstallationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _installation_response(installation)


@router.put("/{app_key}/config", response_model=AppInstallationResponse)
def configure_app(
    app_key: str,
    data: ConfigureAppRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id, app_key)
    try:
        installation = AppInstallationService.configure(db, installation, data.config)
    except AppInstallationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _installation_response(installation)


@router.put("/{app_key}/secret-config", response_model=AppInstallationResponse)
def configure_app_secrets(
    app_key: str,
    data: SetSecretConfigRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Set (or update) the app's encrypted secret config — e.g. WABA
    credentials. Accepts plaintext once over HTTPS, encrypts immediately,
    and never returns it; the response only ever carries
    `secret_config_status` (configured + last-4)."""
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id, app_key)
    try:
        installation = set_secret_config(db, installation, data.secret_config)
    except SecretConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _installation_response(installation)


@router.post("/{app_key}/enable", response_model=AppInstallationResponse)
def enable_app(
    app_key: str,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id, app_key)
    from app.core.scheduler import scheduler
    try:
        installation = AppInstallationService.set_enabled(db, installation, True, scheduler=scheduler)
    except AppInstallationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _installation_response(installation)


@router.post("/{app_key}/disable", response_model=AppInstallationResponse)
def disable_app(
    app_key: str,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id, app_key)
    from app.core.scheduler import scheduler
    installation = AppInstallationService.set_enabled(db, installation, False, scheduler=scheduler)
    return _installation_response(installation)


@router.delete("/{app_key}", status_code=status.HTTP_204_NO_CONTENT)
def uninstall_app(
    app_key: str,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id, app_key)
    from app.core.scheduler import scheduler
    AppInstallationService.uninstall(db, installation, scheduler=scheduler)


@router.post("/{app_key}/run", response_model=AppRunRecordResponse)
def run_app(
    app_key: str,
    data: RunAppRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    user, org = admin_org
    installation = _get_installation_or_404(db, org.id, app_key)
    if not installation.is_enabled:
        raise HTTPException(status_code=400, detail=f"{app_key} is not enabled")

    idempotency_key = data.idempotency_key or f"on_demand:{uuid.uuid4()}"
    run = AppRunner.execute(
        db, installation,
        trigger_type=TRIGGER_ON_DEMAND,
        idempotency_key=idempotency_key,
        triggered_by=user.id,
    )
    return AppRunRecordResponse.model_validate(run)


@router.get("/{app_key}/runs", response_model=AppRunRecordListResponse)
def list_app_runs(
    app_key: str,
    limit: int = Query(20, ge=1, le=100),
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id, app_key)
    runs = (
        db.query(AppRunRecord)
        .filter(AppRunRecord.installation_id == installation.id)
        .order_by(AppRunRecord.started_at.desc())
        .limit(limit)
        .all()
    )
    total = db.query(AppRunRecord).filter(AppRunRecord.installation_id == installation.id).count()
    return AppRunRecordListResponse(
        runs=[AppRunRecordResponse.model_validate(r) for r in runs],
        total=total,
    )
