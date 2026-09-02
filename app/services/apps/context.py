"""Scoped-data-access contract for apps.

An app's run() method receives an AppContext and nothing else — never a raw
DB Session. Every accessor here is a closure over a single `org_id` captured
at construction time, and the underlying Session is captured in the closure
rather than stored as an instance attribute, so there is no `context._db` (or
any other attribute) an app could reach into to escape the org filter. Every
query an app can possibly issue is pre-filtered by org_id before the app ever
sees it.

Any future write/action capability an app needs must be added as a new
closure-based method here, following the exact same pattern — never by
handing out the session.
"""
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    KPIDefinition,
    DataField,
    DataFieldEntry,
    DataEntry,
    WhatsAppRecipient,
    WhatsAppSuppression,
    WhatsAppSendLog,
)


class AppContext:
    """Per-org, per-installation execution context handed to BaseApp.run()."""

    def __init__(
        self,
        db: Session,
        org_id: uuid.UUID,
        installation_id: uuid.UUID,
        config: dict,
        secret_config: dict | None = None,
        run_id: uuid.UUID | None = None,
    ):
        self.org_id = org_id
        self.installation_id = installation_id
        self.config = dict(config or {})
        # Decrypted only by AppRunner at send time, never stored anywhere
        # else — see app/services/app_secret_config.py. Plain dict here is
        # fine (not the Session), same as `config` above.
        self.secret_config = dict(secret_config or {})
        self.run_id = run_id

        def _kpi_query():
            return db.query(KPIDefinition).filter(KPIDefinition.org_id == org_id)

        def _data_field_query():
            return db.query(DataField).filter(DataField.org_id == org_id)

        def _data_entry_query():
            return db.query(DataEntry).filter(DataEntry.org_id == org_id)

        def _data_field_entry_query():
            return db.query(DataFieldEntry).filter(DataFieldEntry.org_id == org_id)

        self.count_kpis = lambda: _kpi_query().count()
        self.list_kpis = lambda: _kpi_query().all()
        self.get_kpi = lambda kpi_id: _kpi_query().filter(KPIDefinition.id == kpi_id).first()

        self.count_data_fields = lambda: _data_field_query().count()
        self.list_data_fields = lambda: _data_field_query().all()
        self.get_data_field = lambda data_field_id: (
            _data_field_query().filter(DataField.id == data_field_id).first()
        )

        self.count_data_entries = lambda: _data_entry_query().count()
        self.latest_data_entry = lambda: (
            _data_entry_query()
            .order_by(DataEntry.date.desc(), DataEntry.created_at.desc())
            .first()
        )

        def _latest_kpi_entry(kpi_id):
            return (
                _data_entry_query()
                .filter(DataEntry.kpi_id == kpi_id)
                .order_by(DataEntry.date.desc(), DataEntry.created_at.desc())
                .first()
            )

        self.latest_kpi_entry = _latest_kpi_entry

        def _latest_data_field_entry(data_field_id):
            return (
                _data_field_entry_query()
                .filter(DataFieldEntry.data_field_id == data_field_id)
                .order_by(DataFieldEntry.date.desc(), DataFieldEntry.created_at.desc())
                .first()
            )

        self.latest_data_field_entry = _latest_data_field_entry

        # --- Recipients (WhatsApp Notifier app: who gets messaged) ---

        def _recipient_query():
            return db.query(WhatsAppRecipient).filter(WhatsAppRecipient.org_id == org_id)

        self.list_recipients = lambda: _recipient_query().order_by(WhatsAppRecipient.name.asc()).all()
        self.get_recipient = lambda recipient_id: (
            _recipient_query().filter(WhatsAppRecipient.id == recipient_id).first()
        )
        self.count_recipients = lambda: _recipient_query().count()

        # --- Suppression list (opt-out) ---

        def _suppression_query():
            return db.query(WhatsAppSuppression).filter(WhatsAppSuppression.org_id == org_id)

        self.is_suppressed = lambda phone: (
            _suppression_query().filter(WhatsAppSuppression.phone == phone).first() is not None
        )
        self.list_suppressed_phones = lambda: [s.phone for s in _suppression_query().all()]

        # --- Per-recipient send log (write) ---

        def _was_sent_this_period(recipient_id, period_bucket: str) -> bool:
            return db.query(WhatsAppSendLog).filter(
                WhatsAppSendLog.org_id == org_id,
                WhatsAppSendLog.recipient_id == recipient_id,
                WhatsAppSendLog.period_bucket == period_bucket,
                WhatsAppSendLog.delivery_status == "sent",
            ).first() is not None

        self.was_sent_this_period = _was_sent_this_period

        def _record_send(
            *, recipient_id=None, recipient_name: str | None = None, phone: str,
            data_value: str | None = None, template_used: str | None = None,
            whatsapp_message_id: str | None = None, delivery_status: str,
            period_bucket: str | None = None, error: str | None = None,
        ) -> WhatsAppSendLog:
            log = WhatsAppSendLog(
                org_id=org_id,
                run_id=run_id,
                recipient_id=recipient_id,
                recipient_name=recipient_name,
                phone=phone,
                data_value=data_value,
                template_used=template_used,
                whatsapp_message_id=whatsapp_message_id,
                delivery_status=delivery_status,
                period_bucket=period_bucket,
                error=error,
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            return log

        self.record_send = _record_send

        # --- Admin write actions (recipients + suppression list) ---
        # Used from admin routes (via a throwaway AppContext, same pattern as
        # AppInstallationService.install/uninstall), not from run() itself.

        def _upsert_recipient(*, name: str, phone: str, notes: str | None = None) -> WhatsAppRecipient:
            existing = _recipient_query().filter(WhatsAppRecipient.phone == phone).first()
            if existing is not None:
                existing.name = name
                existing.notes = notes
                existing.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(existing)
                return existing

            row = WhatsAppRecipient(org_id=org_id, name=name, phone=phone, notes=notes)
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

        self.upsert_recipient = _upsert_recipient

        def _remove_recipient(recipient_id) -> bool:
            existing = _recipient_query().filter(WhatsAppRecipient.id == recipient_id).first()
            if existing is None:
                return False
            db.delete(existing)
            db.commit()
            return True

        self.remove_recipient = _remove_recipient

        def _add_suppression(phone: str, reason: str | None = None) -> WhatsAppSuppression:
            existing = _suppression_query().filter(WhatsAppSuppression.phone == phone).first()
            if existing is not None:
                return existing
            row = WhatsAppSuppression(org_id=org_id, phone=phone, reason=reason)
            db.add(row)
            db.commit()
            db.refresh(row)
            return row

        self.add_suppression = _add_suppression

        def _remove_suppression(phone: str) -> bool:
            existing = _suppression_query().filter(WhatsAppSuppression.phone == phone).first()
            if existing is None:
                return False
            db.delete(existing)
            db.commit()
            return True

        self.remove_suppression = _remove_suppression
