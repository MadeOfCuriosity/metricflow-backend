import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import OrgAppInstallation
from app.services.apps import get_app
from app.services.apps.base import TRIGGER_SCHEDULED

logger = logging.getLogger(__name__)

# Same vocabulary as SyncService.SCHEDULE_INTERVALS.
SCHEDULE_INTERVALS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
}


def _job_id(installation_id) -> str:
    return f"app_{installation_id}"


def _cadence_for(app, installation: OrgAppInstallation) -> str | None:
    """An installation's own `schedule_cadence` config (if the app exposes
    it as a config field and the org set one) overrides the app's class-level
    default_schedule. Falls back to default_schedule so apps that don't offer
    this knob behave exactly as before."""
    configured = (installation.config or {}).get("schedule_cadence")
    if configured in SCHEDULE_INTERVALS:
        return configured
    return app.default_schedule


def add_app_job(scheduler, installation: OrgAppInstallation) -> None:
    """Add or replace the scheduled job for an installation. No-op if the
    app doesn't declare the "scheduled" trigger or has no usable cadence."""
    app = get_app(installation.app_key)
    if TRIGGER_SCHEDULED not in app.triggers:
        return

    cadence = _cadence_for(app, installation)
    interval = SCHEDULE_INTERVALS.get(cadence)
    if not interval:
        return

    job_id = _job_id(installation.id)
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass

    scheduler.add_job(
        _run_scheduled_app,
        "interval",
        seconds=int(interval.total_seconds()),
        id=job_id,
        args=[str(installation.id)],
        replace_existing=True,
        next_run_time=datetime.utcnow() + interval,
    )
    logger.info(f"Scheduled app job for installation {installation.id} ({installation.app_key}) every {app.default_schedule}")


def remove_app_job(scheduler, installation_id) -> None:
    """Remove the scheduled job for an installation, if any. Always safe to
    call — this is the framework-owned teardown step used on disable/uninstall,
    independent of whatever the app's own on_uninstall hook does."""
    job_id = _job_id(installation_id)
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Removed app job for installation {installation_id}")
    except Exception:
        pass


def load_all_scheduled_app_jobs(db: Session, scheduler) -> None:
    """Rehydrate scheduled app jobs on process startup (the job store is
    in-memory and does not survive restarts — mirrors SyncService)."""
    installations = db.query(OrgAppInstallation).filter(
        OrgAppInstallation.is_enabled == True,
    ).all()

    count = 0
    for installation in installations:
        try:
            app = get_app(installation.app_key)
        except ValueError:
            continue
        if TRIGGER_SCHEDULED in app.triggers:
            add_app_job(scheduler, installation)
            count += 1

    logger.info(f"Loaded {count} scheduled app job(s)")


def _run_scheduled_app(installation_id_str: str) -> None:
    """Executed by APScheduler on its own thread — opens its own session."""
    from app.core.database import SessionLocal
    from app.services.app_runner import AppRunner

    db = SessionLocal()
    try:
        installation_id = UUID(installation_id_str)
        installation = db.query(OrgAppInstallation).filter(
            OrgAppInstallation.id == installation_id,
            OrgAppInstallation.is_enabled == True,
        ).first()
        if installation is None:
            # Uninstalled/disabled since the job was scheduled — nothing to do.
            return

        app = get_app(installation.app_key)
        cadence = _cadence_for(app, installation)
        interval = SCHEDULE_INTERVALS.get(cadence)
        # Bucket the idempotency key to the schedule interval so a double-fire
        # within the same tick collides on the unique constraint and no-ops
        # instead of running the app twice.
        bucket = int(datetime.utcnow().timestamp() // interval.total_seconds()) if interval else 0
        idempotency_key = f"scheduled:{bucket}"

        AppRunner.execute(
            db, installation,
            trigger_type=TRIGGER_SCHEDULED,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.error(f"Scheduled app run failed for installation {installation_id_str}: {e}")
    finally:
        db.close()
