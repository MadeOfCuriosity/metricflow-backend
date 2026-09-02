from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import OrgAppInstallation
from app.services.apps import get_app
from app.services.apps.base import TRIGGER_SCHEDULED
from app.services.app_scheduler import add_app_job, remove_app_job


class AppInstallationError(Exception):
    """Raised for invalid app-lifecycle transitions (unknown app, already
    installed, entitlement not granted, etc). Routes translate this to 400s."""


class AppInstallationService:
    """Org-scoped lifecycle management for app installations. Every method
    takes org_id explicitly and every query filters on it."""

    @staticmethod
    def get_all(db: Session, org_id: UUID) -> list[OrgAppInstallation]:
        return db.query(OrgAppInstallation).filter(OrgAppInstallation.org_id == org_id).all()

    @staticmethod
    def get_by_key(db: Session, org_id: UUID, app_key: str) -> OrgAppInstallation | None:
        return db.query(OrgAppInstallation).filter(
            OrgAppInstallation.org_id == org_id,
            OrgAppInstallation.app_key == app_key,
        ).first()

    @staticmethod
    def install(db: Session, org_id: UUID, app_key: str, user_id: UUID | None) -> OrgAppInstallation:
        try:
            app = get_app(app_key)
        except ValueError:
            raise AppInstallationError(f"Unknown app: {app_key}")

        if AppInstallationService.get_by_key(db, org_id, app_key) is not None:
            raise AppInstallationError(f"{app_key} is already installed for this organization")

        installation = OrgAppInstallation(
            org_id=org_id,
            app_key=app_key,
            is_enabled=False,
            entitlement_status="required" if app.requires_entitlement else "not_required",
            config={},
            installed_by=user_id,
        )
        db.add(installation)
        db.commit()
        db.refresh(installation)

        # Best-effort app-specific setup hook — never blocks installation.
        try:
            from app.services.apps.context import AppContext
            context = AppContext(db=db, org_id=org_id, installation_id=installation.id, config={})
            app.on_install(context)
        except Exception:
            pass

        return installation

    @staticmethod
    def configure(db: Session, installation: OrgAppInstallation, config: dict) -> OrgAppInstallation:
        app = get_app(installation.app_key)

        validated: dict = {}
        for field in app.config_schema:
            if field.secret:
                # Secret fields never land in plain `config` — reserved for
                # Fernet-encrypted storage that doesn't exist yet.
                continue
            value = config.get(field.key, field.default)
            if field.required and value is None:
                raise AppInstallationError(f"Missing required config field: {field.key}")
            if value is not None:
                validated[field.key] = value

        installation.config = validated
        installation.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(installation)
        return installation

    @staticmethod
    def set_enabled(db: Session, installation: OrgAppInstallation, enabled: bool, scheduler=None) -> OrgAppInstallation:
        app = get_app(installation.app_key)

        if enabled:
            if installation.entitlement_status in ("required", "revoked"):
                raise AppInstallationError(
                    f"{installation.app_key} requires an entitlement that has not been granted"
                )
            installation.is_enabled = True
            db.commit()
            db.refresh(installation)
            if scheduler is not None and TRIGGER_SCHEDULED in app.triggers:
                add_app_job(scheduler, installation)
        else:
            installation.is_enabled = False
            db.commit()
            db.refresh(installation)
            if scheduler is not None:
                remove_app_job(scheduler, installation.id)

        return installation

    @staticmethod
    def set_entitlement(db: Session, installation: OrgAppInstallation, entitlement_status: str) -> OrgAppInstallation:
        """Manual/superadmin-only entitlement grant — no billing plumbing here."""
        if entitlement_status not in ("not_required", "required", "granted", "revoked"):
            raise AppInstallationError(f"Invalid entitlement_status: {entitlement_status}")

        installation.entitlement_status = entitlement_status
        # Revoking entitlement disables the app immediately — an app can't
        # keep running (on-demand or scheduled) without a granted entitlement
        # once one is required.
        if entitlement_status != "granted" and installation.is_enabled:
            installation.is_enabled = False
        db.commit()
        db.refresh(installation)
        return installation

    @staticmethod
    def uninstall(db: Session, installation: OrgAppInstallation, scheduler=None) -> None:
        """Tear down everything the installation registered — config,
        entitlement state, scheduled jobs, run-state — regardless of what the
        app's own on_uninstall hook does. This ordering guarantees no job can
        fire after this call returns:
          1. Remove the scheduler job unconditionally (framework-owned).
          2. Best-effort call the app's on_uninstall hook.
          3. Hard-delete the installation row (cascades to its run records).
        """
        # 1. Framework-owned teardown — never delegated to the app.
        if scheduler is not None:
            remove_app_job(scheduler, installation.id)

        # 2. App-specific cleanup, best-effort only.
        try:
            app = get_app(installation.app_key)
            from app.services.apps.context import AppContext
            context = AppContext(
                db=db, org_id=installation.org_id, installation_id=installation.id,
                config=installation.config or {},
            )
            app.on_uninstall(context)
        except Exception:
            pass

        # 3. Remove all installation state (config, entitlement, run records
        # via cascade) by deleting the row itself.
        db.delete(installation)
        db.commit()
