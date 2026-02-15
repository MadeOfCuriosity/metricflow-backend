from app.services.connectors.base import BaseConnector, ExternalField, SyncResult
from app.services.connectors.google_sheets import GoogleSheetsConnector
from app.services.connectors.zoho_crm import ZohoCRMConnector
from app.services.connectors.zoho_books import ZohoBooksConnector
from app.services.connectors.zoho_sheet import ZohoSheetConnector
from app.services.connectors.leadsquared import LeadSquaredConnector

CONNECTOR_REGISTRY = {
    "google_sheets": GoogleSheetsConnector,
    "zoho_crm": ZohoCRMConnector,
    "zoho_books": ZohoBooksConnector,
    "zoho_sheet": ZohoSheetConnector,
    "leadsquared": LeadSquaredConnector,
}


def get_connector(integration, db=None) -> BaseConnector:
    """Factory: return the correct connector instance for an integration."""
    connector_cls = CONNECTOR_REGISTRY.get(integration.provider)
    if connector_cls is None:
        raise ValueError(f"Unknown provider: {integration.provider}")
    return connector_cls(integration, db)


__all__ = [
    "BaseConnector",
    "ExternalField",
    "SyncResult",
    "GoogleSheetsConnector",
    "ZohoCRMConnector",
    "ZohoBooksConnector",
    "ZohoSheetConnector",
    "LeadSquaredConnector",
    "get_connector",
]
