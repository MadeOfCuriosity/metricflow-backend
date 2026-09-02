from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.apps.context import AppContext

# Trigger types an app may declare it runs under.
# "on_demand" and "scheduled" are live. "event" is reserved: an app may declare
# it, but no event bus exists yet, so it is inert until one is built — no
# change to BaseApp or the installation model will be needed when it is wired.
TRIGGER_ON_DEMAND = "on_demand"
TRIGGER_SCHEDULED = "scheduled"
TRIGGER_EVENT = "event"
VALID_TRIGGERS = {TRIGGER_ON_DEMAND, TRIGGER_SCHEDULED, TRIGGER_EVENT}

# Cadences supported by the scheduler integration, mirroring Integration.sync_schedule.
SCHEDULE_CHOICES = {"1h", "6h", "12h", "24h"}
SCHEDULE_SECONDS = {"1h": 3600, "6h": 21600, "12h": 43200, "24h": 86400}


def compute_period_bucket(cadence: str | None) -> str:
    """Deterministic id for "the current period" of a schedule cadence, e.g.
    "24h:19980" — stable for the whole interval, changes once it elapses.
    Lives here (not app_scheduler.py) so apps can compute it for per-recipient
    dedup without importing the scheduler module and risking a circular
    import through the app registry."""
    import time
    seconds = SCHEDULE_SECONDS.get(cadence)
    if not seconds:
        return "none:0"
    return f"{cadence}:{int(time.time() // seconds)}"


@dataclass
class AppConfigField:
    """Declares one field of an app's configuration schema."""
    key: str
    label: str
    field_type: str  # "string" | "number" | "boolean" | "select"
    required: bool = False
    # Secret fields are destined for encrypted storage (reserved — no Fernet
    # plumbing wired yet). The framework keeps them out of plain `config` even
    # today, so wiring encryption later needs no data migration.
    secret: bool = False
    options: list[str] | None = None  # choices, when field_type == "select"
    default: Any = None
    help_text: str | None = None


@dataclass
class AppRunResult:
    """What an app's run() returns; the runner turns this into an AppRunRecord."""
    status: str  # "success" | "partial" | "failed"
    summary: str = ""
    data: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class BaseApp(ABC):
    """Base interface for a first-party, in-process app/extension.

    Mirrors BaseConnector: a small declarative surface plus one execution
    entrypoint. Apps are registered by key in apps/__init__.py-style registry
    (app/services/apps/__init__.py) — no dynamic loading, no sandboxing.
    """

    key: str
    name: str
    description: str
    requires_entitlement: bool = False
    config_schema: list[AppConfigField] = []

    # True for internal-only apps that exist to exercise the framework
    # (e.g. reference_health). Registered so they're installable/runnable in
    # tests and local dev, but excluded from the org-facing app listing.
    dev_only: bool = False

    # Subset of TRIGGER_ON_DEMAND / TRIGGER_SCHEDULED / TRIGGER_EVENT this app runs under.
    triggers: list[str] = [TRIGGER_ON_DEMAND]

    # Cadence used when "scheduled" is in triggers. One of SCHEDULE_CHOICES.
    default_schedule: str | None = None

    @abstractmethod
    def run(self, context: "AppContext") -> AppRunResult:
        """Execute the app for one org. `context` is the only thing an app
        ever touches — it never receives a raw DB Session."""
        ...

    def on_install(self, context: "AppContext") -> None:
        """Optional hook invoked once after the installation row is created.
        Default no-op — safe to leave unimplemented."""
        return None

    def on_uninstall(self, context: "AppContext") -> None:
        """Optional hook invoked before the installation row is torn down.
        Default no-op. The framework — not this hook — is responsible for
        removing scheduled jobs, entitlement state, and installation/run
        records, so doing nothing here is always safe."""
        return None
