"""THROWAWAY REFERENCE APP — NEVER SHIP THIS.

Exists only to prove the Apps framework end to end: it reads a count of the
org's KPIs via the org-scoped AppContext and returns it. It sends nothing,
writes nothing, and has no side effects. Delete it once a real first-party
app is built on this framework.
"""
from app.services.apps.base import AppConfigField, AppRunResult, BaseApp, TRIGGER_ON_DEMAND, TRIGGER_SCHEDULED
from app.services.apps.context import AppContext


class ReferenceHealthApp(BaseApp):
    key = "reference_health"
    name = "Reference Health Check (dev only — never ship)"
    description = (
        "Throwaway reference app that reads a count of the org's KPI definitions "
        "to prove the app framework works end to end. Never ship this."
    )
    requires_entitlement = False
    dev_only = True
    config_schema: list[AppConfigField] = [
        AppConfigField(
            key="greeting",
            label="Greeting prefix",
            field_type="string",
            required=False,
            default="Health check",
            help_text="Prefixes the run summary — purely cosmetic, proves config plumbing works.",
        ),
    ]
    triggers = [TRIGGER_ON_DEMAND, TRIGGER_SCHEDULED]
    default_schedule = "24h"

    def run(self, context: AppContext) -> AppRunResult:
        kpi_count = context.count_kpis()
        greeting = context.config.get("greeting") or "Health check"
        return AppRunResult(
            status="success",
            summary=f"{greeting}: org has {kpi_count} KPI definition(s).",
            data={"kpi_count": kpi_count},
        )
