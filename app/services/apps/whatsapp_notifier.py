"""WhatsApp Notifier — the first real tenant of the Apps framework. Generic
by design: at setup time an admin connects one existing KPI or Data Field
as the data source, and maintains a recipient list (name, phone, notes)
inside the app. Each scheduled/on-demand run reads the source's latest
value and sends it, via the org's OWN WhatsApp Business Account, to every
recipient not suppressed and not already messaged this period.

The same mechanism covers different use cases purely through configuration:
- Receivables/credit-sales reminders: connect a "receivables outstanding"
  KPI or Data Field, add customers as recipients.
- Recurring reports: connect any KPI (e.g. daily revenue), add stakeholders
  as recipients, leave the threshold unset so it sends every run.
An optional threshold (only send when the value crosses a bound) supports
the reminder case; leaving it unset makes every run a broadcast/report.

Architectural constraint (do not change): every send goes out through the
installing org's own WABA credentials (Step 3 secret config), never a
shared Visualize-owned number.
"""
import logging
import time

from app.services.apps.base import (
    AppConfigField,
    AppRunResult,
    BaseApp,
    TRIGGER_ON_DEMAND,
    TRIGGER_SCHEDULED,
    SCHEDULE_CHOICES,
    compute_period_bucket,
)
from app.services.apps.context import AppContext
from app.services.whatsapp_client import send_template_message, WhatsAppSendError

logger = logging.getLogger(__name__)

# Small pause between sends to stay well under Meta's per-second rate limits.
SEND_THROTTLE_SECONDS = 0.3

DATA_SOURCE_KINDS = ("kpi", "data_field")
THRESHOLD_COMPARISONS = ("none", "gte", "lte")


class WhatsAppNotifierApp(BaseApp):
    key = "whatsapp_notifier"
    name = "WhatsApp Notifier"
    description = (
        "Sends a WhatsApp message built from an existing KPI or Data Field's latest value "
        "to a recipient list you manage in-app, via the org's own WhatsApp Business Account. "
        "Configure it as a receivables/credit-sales reminder, a recurring report, or anything "
        "in between — the mechanism is the same, only the data source, threshold, and recipients differ."
    )
    requires_entitlement = True
    triggers = [TRIGGER_ON_DEMAND, TRIGGER_SCHEDULED]
    default_schedule = "24h"

    config_schema: list[AppConfigField] = [
        AppConfigField(
            key="data_source_kind",
            label="Data source type",
            field_type="select",
            required=True,
            options=list(DATA_SOURCE_KINDS),
            help_text="Whether the connected data source is a KPI or a raw Data Field.",
        ),
        AppConfigField(
            key="data_source_id",
            label="Data source ID",
            field_type="string",
            required=True,
            help_text="The KPI or Data Field to pull the latest value from. Set via the app's "
                       "\"Manage Data\" panel, which lists your existing KPIs/Data Fields to pick from.",
        ),
        AppConfigField(
            key="template_name",
            label="Approved WhatsApp template name",
            field_type="string",
            required=True,
            help_text="Exact name of the pre-approved utility template in WhatsApp Manager. "
                       "Its body must take 3 variables in order: recipient name, data value, note/date.",
        ),
        AppConfigField(
            key="threshold_comparison",
            label="Only send when value is...",
            field_type="select",
            required=False,
            default="none",
            options=list(THRESHOLD_COMPARISONS),
            help_text="\"none\" sends every run regardless of value (e.g. a recurring report). "
                       "\"gte\"/\"lte\" only sends when the latest value crosses threshold_value "
                       "(e.g. a receivables reminder: only send when outstanding >= some amount).",
        ),
        AppConfigField(
            key="threshold_value",
            label="Threshold value",
            field_type="number",
            required=False,
            help_text="Required only if \"Only send when value is\" isn't \"none\".",
        ),
        AppConfigField(
            key="schedule_cadence",
            label="Check frequency",
            field_type="select",
            required=False,
            default="24h",
            options=sorted(SCHEDULE_CHOICES),
            help_text="How often the scheduled trigger re-checks the data source and sends.",
        ),
        AppConfigField(
            key="waba_phone_number_id",
            label="WABA phone number ID",
            field_type="string",
            required=True,
            secret=True,
            help_text="From your WhatsApp Business Account in Meta Business Manager.",
        ),
        AppConfigField(
            key="waba_access_token",
            label="WABA access token",
            field_type="string",
            required=True,
            secret=True,
            help_text="Permanent system-user access token for your WABA. Stored encrypted, never shown again.",
        ),
        AppConfigField(
            key="template_namespace",
            label="Template namespace",
            field_type="string",
            required=False,
            secret=True,
            help_text="Only required for older WABA setups that still use namespace-qualified templates.",
        ),
    ]

    def _latest_value(self, context: AppContext):
        """Returns (value, as_of_date) from the configured data source, or
        (None, None) if nothing has been recorded yet."""
        kind = context.config.get("data_source_kind")
        source_id = context.config.get("data_source_id")

        if kind == "kpi":
            entry = context.latest_kpi_entry(source_id)
            if entry is None:
                return None, None
            return entry.calculated_value, entry.date
        elif kind == "data_field":
            entry = context.latest_data_field_entry(source_id)
            if entry is None:
                return None, None
            return entry.value, entry.date
        return None, None

    def run(self, context: AppContext) -> AppRunResult:
        phone_number_id = context.secret_config.get("waba_phone_number_id")
        access_token = context.secret_config.get("waba_access_token")
        template_namespace = context.secret_config.get("template_namespace") or None
        template_name = context.config.get("template_name")

        if not phone_number_id or not access_token:
            return AppRunResult(
                status="failed",
                summary="WABA credentials are not configured — connect a WhatsApp Business Account first.",
                errors=["Missing waba_phone_number_id or waba_access_token in secret config"],
            )
        if not template_name:
            return AppRunResult(
                status="failed",
                summary="No approved WhatsApp template configured.",
                errors=["Missing template_name in config"],
            )

        kind = context.config.get("data_source_kind")
        source_id = context.config.get("data_source_id")
        if kind not in DATA_SOURCE_KINDS or not source_id:
            return AppRunResult(
                status="failed",
                summary="No data source connected — pick a KPI or Data Field in the app's Manage Data panel.",
                errors=["Missing or invalid data_source_kind/data_source_id in config"],
            )

        value, as_of_date = self._latest_value(context)
        if value is None:
            return AppRunResult(
                status="success",
                summary="No data recorded yet for the connected source — nothing to send.",
                data={"sent": 0, "threshold_met": False},
            )

        comparison = context.config.get("threshold_comparison") or "none"
        threshold_value = context.config.get("threshold_value")
        if comparison != "none" and threshold_value is not None:
            threshold_value = float(threshold_value)
            met = value >= threshold_value if comparison == "gte" else value <= threshold_value
            if not met:
                return AppRunResult(
                    status="success",
                    summary=f"Threshold not met (value={value}, threshold={threshold_value}) — nothing sent.",
                    data={"sent": 0, "threshold_met": False, "value": value},
                )

        recipients = context.list_recipients()
        if not recipients:
            return AppRunResult(
                status="success",
                summary="No recipients configured yet.",
                data={"sent": 0, "threshold_met": True, "value": value},
            )

        cadence = context.config.get("schedule_cadence") or self.default_schedule
        period_bucket = compute_period_bucket(cadence)
        value_str = f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)

        sent = 0
        failed = 0
        skipped_suppressed = 0
        skipped_duplicate = 0
        errors: list[str] = []

        for recipient in recipients:
            phone = recipient.phone

            if context.is_suppressed(phone):
                skipped_suppressed += 1
                context.record_send(
                    recipient_id=recipient.id,
                    recipient_name=recipient.name,
                    phone=phone,
                    data_value=value_str,
                    template_used=template_name,
                    delivery_status="skipped_suppressed",
                    period_bucket=period_bucket,
                )
                continue

            if context.was_sent_this_period(recipient.id, period_bucket):
                skipped_duplicate += 1
                continue

            note_or_date = recipient.notes or (as_of_date.isoformat() if as_of_date else "")
            variables = [recipient.name, value_str, note_or_date]
            try:
                message_id = send_template_message(
                    phone_number_id=phone_number_id,
                    access_token=access_token,
                    to_phone=phone,
                    template_name=template_name,
                    template_namespace=template_namespace,
                    template_variables=variables,
                )
                context.record_send(
                    recipient_id=recipient.id,
                    recipient_name=recipient.name,
                    phone=phone,
                    data_value=value_str,
                    template_used=template_name,
                    whatsapp_message_id=message_id,
                    delivery_status="sent",
                    period_bucket=period_bucket,
                )
                sent += 1
            except WhatsAppSendError as e:
                failed += 1
                error_msg = str(e)[:500]
                errors.append(f"{recipient.name}: {error_msg}")
                context.record_send(
                    recipient_id=recipient.id,
                    recipient_name=recipient.name,
                    phone=phone,
                    data_value=value_str,
                    template_used=template_name,
                    delivery_status="failed",
                    period_bucket=period_bucket,
                    error=error_msg,
                )

            if len(recipients) > 1:
                time.sleep(SEND_THROTTLE_SECONDS)

        if sent == 0 and failed > 0:
            status = "failed"
            summary = f"All {failed} send(s) failed."
        elif failed > 0:
            status = "partial"
            summary = f"Sent {sent}, failed {failed}, skipped {skipped_suppressed} suppressed."
        else:
            status = "success"
            summary = f"Sent {sent} message(s) with value {value_str}."

        return AppRunResult(
            status=status,
            summary=summary,
            data={
                "sent": sent,
                "failed": failed,
                "skipped_suppressed": skipped_suppressed,
                "skipped_duplicate": skipped_duplicate,
                "threshold_met": True,
                "value": value,
            },
            errors=errors,
        )
