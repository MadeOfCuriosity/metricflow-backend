import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AppRunRecord, OrgAppInstallation
from app.services.apps import get_app
from app.services.apps.context import AppContext
from app.services.app_secret_config import get_secret_config

logger = logging.getLogger(__name__)


class AppRunner:
    """Executes apps through the durable run-record spine.

    This is the only code path allowed to call BaseApp.run() — it constructs
    the org-scoped AppContext and hands the app nothing else. Every execution
    (on-demand or scheduled) goes through here so the run-record is always
    the source of truth for what ran, for which org, and with what result.
    """

    @staticmethod
    def cleanup_stale_runs(db: Session, timeout_minutes: int = 30) -> int:
        """Mark runs stuck in 'running' for too long as 'failed' (mirrors SyncService)."""
        cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)
        count = db.query(AppRunRecord).filter(
            AppRunRecord.status == "running",
            AppRunRecord.started_at < cutoff,
        ).update({
            "status": "failed",
            "completed_at": datetime.utcnow(),
            "error": "Run timed out (process may have crashed)",
        })
        if count > 0:
            db.commit()
            logger.warning(f"Cleaned up {count} stale app run(s)")
        return count

    @staticmethod
    def execute(
        db: Session,
        installation: OrgAppInstallation,
        trigger_type: str,
        idempotency_key: str,
        triggered_by: UUID | None = None,
    ) -> AppRunRecord:
        """Run `installation`'s app once, idempotently keyed on
        (installation_id, idempotency_key).

        If a run with this exact key already exists, it is returned as-is
        instead of re-executing the app — this is what makes retries and
        duplicate fires (e.g. a scheduler double-tick) safe: the app's run()
        never executes twice for the same logical invocation.
        """
        AppRunner.cleanup_stale_runs(db)

        existing = db.query(AppRunRecord).filter(
            AppRunRecord.installation_id == installation.id,
            AppRunRecord.idempotency_key == idempotency_key,
        ).first()
        if existing is not None:
            return existing

        run = AppRunRecord(
            installation_id=installation.id,
            org_id=installation.org_id,
            app_key=installation.app_key,
            status="running",
            trigger_type=trigger_type,
            triggered_by=triggered_by,
            idempotency_key=idempotency_key,
            started_at=datetime.utcnow(),
        )
        db.add(run)
        try:
            db.commit()
        except IntegrityError:
            # Concurrent duplicate fire raced us to create the row first.
            db.rollback()
            existing = db.query(AppRunRecord).filter(
                AppRunRecord.installation_id == installation.id,
                AppRunRecord.idempotency_key == idempotency_key,
            ).first()
            if existing is not None:
                return existing
            raise
        db.refresh(run)

        try:
            app = get_app(installation.app_key)
            # Secret config is decrypted here, at send time, and handed to
            # the app only via the AppContext closure — it is never returned
            # by any API response and never persisted anywhere in plaintext.
            context = AppContext(
                db=db,
                org_id=installation.org_id,
                installation_id=installation.id,
                config=installation.config or {},
                secret_config=get_secret_config(installation),
                run_id=run.id,
            )
            result = app.run(context)
            run.status = result.status
            run.summary = result.summary
            run.result = result.data
            if result.errors:
                run.error = "; ".join(result.errors)
        except Exception as e:
            logger.error(
                f"App run failed for installation {installation.id} ({installation.app_key}): {e}",
                exc_info=True,
            )
            run.status = "failed"
            run.error = str(e)[:2000]
        finally:
            run.completed_at = datetime.utcnow()
            db.commit()
            db.refresh(run)

        return run
