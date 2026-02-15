import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.integration import Integration
from app.models.integration_field_mapping import IntegrationFieldMapping
from app.models.sync_log import SyncLog
from app.models.data_field_entry import DataFieldEntry
from app.services.connectors import get_connector
from app.services.entry_service import EntryService

logger = logging.getLogger(__name__)

# Map schedule strings to timedelta intervals
SCHEDULE_INTERVALS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
}


class SyncService:
    """Orchestrates data syncing from external sources into DataFieldEntry."""

    @staticmethod
    def execute_sync(
        db: Session,
        integration_id: UUID,
        triggered_by: UUID | None = None,
        trigger_type: str = "manual",
    ) -> SyncLog:
        """
        Main sync logic:
        1. Create SyncLog(status=running)
        2. Instantiate connector
        3. Refresh auth
        4. Fetch data
        5. Upsert into DataFieldEntry
        6. Recalculate affected KPIs
        7. Update logs and integration
        """
        integration = db.query(Integration).filter(
            Integration.id == integration_id,
        ).first()

        if not integration:
            raise ValueError(f"Integration {integration_id} not found")

        # Create sync log
        sync_log = SyncLog(
            integration_id=integration.id,
            status="running",
            trigger_type=trigger_type,
            triggered_by=triggered_by,
            started_at=datetime.utcnow(),
        )
        db.add(sync_log)
        db.commit()
        db.refresh(sync_log)

        # Get active field mappings
        mappings = db.query(IntegrationFieldMapping).filter(
            IntegrationFieldMapping.integration_id == integration.id,
            IntegrationFieldMapping.is_active == True,
        ).all()

        if not mappings:
            sync_log.status = "failed"
            sync_log.completed_at = datetime.utcnow()
            sync_log.summary = "No active field mappings configured"
            db.commit()
            return sync_log

        try:
            # Instantiate connector
            connector = get_connector(integration, db)

            # Refresh auth
            auth_ok = connector.refresh_auth()
            if not auth_ok:
                sync_log.status = "failed"
                sync_log.completed_at = datetime.utcnow()
                sync_log.summary = "Authentication failed. Please reconnect."
                integration.status = "error"
                integration.error_message = "Authentication failed"
                db.commit()
                return sync_log

            # Determine date range
            if integration.last_synced_at:
                start_date = integration.last_synced_at.date() - timedelta(days=1)
            else:
                start_date = date.today() - timedelta(days=30)
            end_date = date.today()

            # Fetch data
            raw_data = connector.fetch_data(start_date, end_date)
            sync_log.rows_fetched = len(raw_data)

            if not raw_data:
                sync_log.status = "success"
                sync_log.completed_at = datetime.utcnow()
                sync_log.summary = "No data found in the specified date range"
                integration.last_synced_at = datetime.utcnow()
                SyncService._update_next_sync(integration)
                db.commit()
                return sync_log

            # Process data: upsert DataFieldEntry rows
            rows_written = 0
            rows_skipped = 0
            errors = []
            affected_dates_fields: dict[date, set[UUID]] = defaultdict(set)

            for row in raw_data:
                row_date = row.get("date")
                if not isinstance(row_date, date):
                    rows_skipped += 1
                    continue

                for mapping in mappings:
                    try:
                        value = SyncService._extract_value(
                            row, mapping.external_field_name, mapping.aggregation
                        )
                        if value is None:
                            rows_skipped += 1
                            continue

                        # Upsert into DataFieldEntry
                        existing = db.query(DataFieldEntry).filter(
                            DataFieldEntry.org_id == integration.org_id,
                            DataFieldEntry.data_field_id == mapping.data_field_id,
                            DataFieldEntry.date == row_date,
                        ).first()

                        if existing:
                            existing.value = value
                            existing.entered_by = None  # Mark as synced (not manual)
                        else:
                            entry = DataFieldEntry(
                                org_id=integration.org_id,
                                data_field_id=mapping.data_field_id,
                                date=row_date,
                                value=value,
                                entered_by=None,
                            )
                            db.add(entry)

                        db.flush()
                        rows_written += 1
                        affected_dates_fields[row_date].add(mapping.data_field_id)

                    except Exception as e:
                        errors.append(
                            f"Row {row_date}, field {mapping.external_field_name}: {str(e)}"
                        )

            # Recalculate affected KPIs for each date
            kpis_recalculated = 0
            for entry_date, field_ids in affected_dates_fields.items():
                try:
                    count = EntryService._recalculate_kpis(
                        db, integration.org_id, triggered_by, entry_date, field_ids
                    )
                    kpis_recalculated += count
                except Exception as e:
                    errors.append(f"KPI recalc for {entry_date}: {str(e)}")

            db.commit()

            # Update sync log
            sync_log.rows_written = rows_written
            sync_log.rows_skipped = rows_skipped
            sync_log.errors_count = len(errors)
            sync_log.error_details = errors if errors else None
            sync_log.status = "success" if not errors else "partial"
            sync_log.completed_at = datetime.utcnow()
            sync_log.summary = (
                f"Synced {rows_written} values across {len(affected_dates_fields)} dates. "
                f"{kpis_recalculated} KPIs recalculated."
            )

            # Update integration
            integration.last_synced_at = datetime.utcnow()
            integration.status = "connected"
            integration.error_message = None
            SyncService._update_next_sync(integration)
            db.commit()

            return sync_log

        except Exception as e:
            logger.error(f"Sync failed for integration {integration_id}: {e}", exc_info=True)
            sync_log.status = "failed"
            sync_log.completed_at = datetime.utcnow()
            sync_log.errors_count = 1
            sync_log.error_details = [str(e)]
            sync_log.summary = f"Sync failed: {str(e)}"
            integration.status = "error"
            integration.error_message = str(e)[:500]
            db.commit()
            return sync_log

    @staticmethod
    def _extract_value(row: dict, field_name: str, aggregation: str) -> float | None:
        """Extract a value from a data row based on field name and aggregation type."""
        if aggregation == "direct":
            val = row.get(field_name)
            if isinstance(val, (int, float)):
                return float(val)
            return None

        if aggregation == "count":
            # Use pre-computed record count
            return float(row.get("__record_count", 0))

        # For sum/avg/min/max — use pre-computed aggregations from CRM connectors
        agg_key = f"{field_name}__{aggregation}"
        val = row.get(agg_key)
        if isinstance(val, (int, float)):
            return float(val)

        return None

    @staticmethod
    def _update_next_sync(integration: Integration) -> None:
        """Calculate and set the next sync time based on schedule."""
        interval = SCHEDULE_INTERVALS.get(integration.sync_schedule)
        if interval:
            integration.next_sync_at = datetime.utcnow() + interval
        else:
            integration.next_sync_at = None

    # --- Scheduler Integration ---

    @staticmethod
    def load_all_scheduled_jobs(db: Session, scheduler) -> None:
        """Load all scheduled integration jobs on startup."""
        integrations = db.query(Integration).filter(
            Integration.sync_schedule != "manual",
            Integration.status == "connected",
        ).all()

        for integration in integrations:
            SyncService.add_sync_job(scheduler, integration)

        logger.info(f"Loaded {len(integrations)} scheduled sync jobs")

    @staticmethod
    def add_sync_job(scheduler, integration: Integration) -> None:
        """Add or update a scheduled sync job for an integration."""
        job_id = f"sync_{integration.id}"
        interval = SCHEDULE_INTERVALS.get(integration.sync_schedule)

        if not interval:
            # Remove job if schedule is manual
            SyncService.remove_sync_job(scheduler, integration.id)
            return

        # Remove existing job if any
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

        scheduler.add_job(
            SyncService._run_scheduled_sync,
            "interval",
            seconds=int(interval.total_seconds()),
            id=job_id,
            args=[str(integration.id)],
            replace_existing=True,
            next_run_time=datetime.utcnow() + interval,
        )
        logger.info(f"Scheduled sync job for integration {integration.id} every {integration.sync_schedule}")

    @staticmethod
    def remove_sync_job(scheduler, integration_id: UUID) -> None:
        """Remove a scheduled sync job."""
        job_id = f"sync_{integration_id}"
        try:
            scheduler.remove_job(job_id)
            logger.info(f"Removed sync job for integration {integration_id}")
        except Exception:
            pass

    @staticmethod
    def _run_scheduled_sync(integration_id_str: str) -> None:
        """Execute a scheduled sync (called by APScheduler)."""
        db = SessionLocal()
        try:
            integration_id = UUID(integration_id_str)
            SyncService.execute_sync(
                db, integration_id,
                triggered_by=None,
                trigger_type="scheduled",
            )
        except Exception as e:
            logger.error(f"Scheduled sync failed for {integration_id_str}: {e}")
        finally:
            db.close()
