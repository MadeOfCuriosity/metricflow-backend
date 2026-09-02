from app.services.apps.base import BaseApp
from app.services.apps.reference_health import ReferenceHealthApp
from app.services.apps.whatsapp_notifier import WhatsAppNotifierApp

# Name-based registry, mirroring app/services/connectors/__init__.py.
# First-party, in-process apps only — add a new entry here to register an app.
APP_REGISTRY: dict[str, type[BaseApp]] = {
    "reference_health": ReferenceHealthApp,
    "whatsapp_notifier": WhatsAppNotifierApp,
}


def get_app(app_key: str) -> BaseApp:
    app_cls = APP_REGISTRY.get(app_key)
    if app_cls is None:
        raise ValueError(f"Unknown app: {app_key}")
    return app_cls()


def list_apps() -> list[BaseApp]:
    return [cls() for cls in APP_REGISTRY.values()]


__all__ = ["BaseApp", "APP_REGISTRY", "get_app", "list_apps"]
