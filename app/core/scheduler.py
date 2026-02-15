import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(
    jobstores={"default": MemoryJobStore()},
    job_defaults={"coalesce": True, "max_instances": 1},
)


def start_scheduler():
    """Start the scheduler and load existing integration sync jobs."""
    from app.core.database import SessionLocal
    from app.services.sync_service import SyncService

    db = SessionLocal()
    try:
        SyncService.load_all_scheduled_jobs(db, scheduler)
    except Exception as e:
        logger.error(f"Failed to load scheduled sync jobs: {e}")
    finally:
        db.close()

    scheduler.start()
    logger.info("APScheduler started for integration syncs")


def shutdown_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")
