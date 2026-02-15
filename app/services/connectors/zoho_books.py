import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app.core.config import settings
from app.core.encryption import encrypt_value, decrypt_value
from app.services.connectors.base import BaseConnector, ExternalField

logger = logging.getLogger(__name__)

ZOHO_AUTH_URI = "https://accounts.zoho.com/oauth/v2/auth"
ZOHO_TOKEN_URI = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_BOOKS_API_BASE = "https://www.zohoapis.com/books/v3"
ZOHO_BOOKS_SCOPES = "ZohoBooks.fullaccess.all"

ZOHO_DATE_FORMAT = "%Y-%m-%d"

# Zoho Books modules and their API endpoints + date fields
BOOKS_MODULES = {
    "invoices": {"endpoint": "invoices", "date_field": "date", "id_field": "invoice_id"},
    "bills": {"endpoint": "bills", "date_field": "date", "id_field": "bill_id"},
    "expenses": {"endpoint": "expenses", "date_field": "date", "id_field": "expense_id"},
    "payments_received": {"endpoint": "customerpayments", "date_field": "date", "id_field": "payment_id"},
    "payments_made": {"endpoint": "vendorpayments", "date_field": "date", "id_field": "payment_id"},
    "credit_notes": {"endpoint": "creditnotes", "date_field": "date", "id_field": "creditnote_id"},
    "sales_orders": {"endpoint": "salesorders", "date_field": "date", "id_field": "salesorder_id"},
    "purchase_orders": {"endpoint": "purchaseorders", "date_field": "date", "id_field": "purchaseorder_id"},
}


class ZohoBooksConnector(BaseConnector):
    """Connector for Zoho Books API v3."""

    @staticmethod
    def get_authorize_url(state: str) -> str:
        """Generate OAuth2 authorization URL for Zoho Books."""
        params = {
            "scope": ZOHO_BOOKS_SCOPES,
            "client_id": settings.ZOHO_OAUTH_CLIENT_ID,
            "response_type": "code",
            "access_type": "offline",
            "redirect_uri": settings.ZOHO_BOOKS_OAUTH_REDIRECT_URI,
            "state": state,
            "prompt": "consent",
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{ZOHO_AUTH_URI}?{query}"

    @staticmethod
    def exchange_code(code: str) -> dict:
        """Exchange authorization code for access + refresh tokens."""
        with httpx.Client() as client:
            resp = client.post(
                ZOHO_TOKEN_URI,
                params={
                    "code": code,
                    "client_id": settings.ZOHO_OAUTH_CLIENT_ID,
                    "client_secret": settings.ZOHO_OAUTH_CLIENT_SECRET,
                    "redirect_uri": settings.ZOHO_BOOKS_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    def _get_org_id(self) -> str:
        """Get the Zoho Books organization ID from config."""
        config = self.integration.config or {}
        return config.get("zoho_org_id", "")

    def _get_headers(self) -> dict:
        """Get authorization headers with the current access token."""
        access_token = decrypt_value(self.integration.access_token_encrypted) if self.integration.access_token_encrypted else ""
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        }

    def test_connection(self) -> bool:
        """Test connection by fetching organizations from Zoho Books."""
        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{ZOHO_BOOKS_API_BASE}/organizations",
                    headers=self._get_headers(),
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("code") == 0
                return False
        except Exception as e:
            logger.error(f"Zoho Books connection test failed: {e}")
            return False

    def refresh_auth(self) -> bool:
        """Refresh the OAuth access token."""
        refresh_token = decrypt_value(self.integration.refresh_token_encrypted) if self.integration.refresh_token_encrypted else None
        if not refresh_token:
            return False

        try:
            with httpx.Client() as client:
                resp = client.post(
                    ZOHO_TOKEN_URI,
                    params={
                        "refresh_token": refresh_token,
                        "client_id": settings.ZOHO_OAUTH_CLIENT_ID,
                        "client_secret": settings.ZOHO_OAUTH_CLIENT_SECRET,
                        "grant_type": "refresh_token",
                    },
                )
                resp.raise_for_status()
                tokens = resp.json()

            if "access_token" not in tokens:
                logger.error(f"Zoho Books refresh failed: {tokens}")
                return False

            if self.db and self.integration:
                self.integration.access_token_encrypted = encrypt_value(tokens["access_token"])
                expires_in = tokens.get("expires_in", 3600)
                self.integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                self.db.commit()

            return True
        except Exception as e:
            logger.error(f"Zoho Books token refresh failed: {e}")
            return False

    def get_available_fields(self) -> list[ExternalField]:
        """Return available fields for the configured Zoho Books module."""
        config = self.integration.config or {}
        module = config.get("module", "invoices")
        module_info = BOOKS_MODULES.get(module, BOOKS_MODULES["invoices"])
        org_id = self._get_org_id()

        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{ZOHO_BOOKS_API_BASE}/{module_info['endpoint']}",
                    headers=self._get_headers(),
                    params={"organization_id": org_id, "page": 1, "per_page": 1},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

            # Extract fields from the first record to discover available fields
            records = data.get(module_info["endpoint"], data.get("data", []))
            if not records:
                # Return common fields for the module
                return self._get_default_fields(module)

            sample = records[0]
            fields = []
            for key, val in sample.items():
                if key.startswith("_") or isinstance(val, (dict, list)):
                    continue
                field_type = "string"
                if isinstance(val, (int, float)):
                    field_type = "number"
                elif isinstance(val, bool):
                    field_type = "boolean"
                elif key in ("date", "due_date", "created_time", "last_modified_time"):
                    field_type = "date"

                fields.append(ExternalField(
                    name=key,
                    label=key.replace("_", " ").title(),
                    field_type=field_type,
                ))
            return fields

        except Exception as e:
            logger.error(f"Failed to fetch Zoho Books fields: {e}")
            return self._get_default_fields(module)

    def _get_default_fields(self, module: str) -> list[ExternalField]:
        """Return common default fields for a module."""
        common = [
            ExternalField(name="total", label="Total", field_type="number"),
            ExternalField(name="balance", label="Balance", field_type="number"),
            ExternalField(name="status", label="Status", field_type="string"),
            ExternalField(name="date", label="Date", field_type="date"),
        ]
        if module in ("invoices", "credit_notes", "sales_orders"):
            common.extend([
                ExternalField(name="sub_total", label="Sub Total", field_type="number"),
                ExternalField(name="tax_total", label="Tax Total", field_type="number"),
            ])
        if module == "expenses":
            common.extend([
                ExternalField(name="amount", label="Amount", field_type="number"),
            ])
        return common

    def fetch_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Fetch records from the configured Zoho Books module, aggregate by date.
        Returns list of dicts with "date" key and aggregated values.
        """
        config = self.integration.config or {}
        module = config.get("module", "invoices")
        module_info = BOOKS_MODULES.get(module, BOOKS_MODULES["invoices"])
        org_id = self._get_org_id()
        date_field = config.get("date_field", module_info["date_field"])

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        all_records = []
        page = 1

        try:
            with httpx.Client(timeout=30) as client:
                while True:
                    params = {
                        "organization_id": org_id,
                        "date_start": start_date.strftime(ZOHO_DATE_FORMAT),
                        "date_end": end_date.strftime(ZOHO_DATE_FORMAT),
                        "page": page,
                        "per_page": 200,
                        "sort_column": date_field,
                        "sort_order": "A",
                    }

                    resp = client.get(
                        f"{ZOHO_BOOKS_API_BASE}/{module_info['endpoint']}",
                        headers=self._get_headers(),
                        params=params,
                    )

                    if resp.status_code == 204:
                        break
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("code") != 0:
                        logger.error(f"Zoho Books API error: {data.get('message')}")
                        break

                    records = data.get(module_info["endpoint"], data.get("data", []))
                    all_records.extend(records)

                    page_context = data.get("page_context", {})
                    if not page_context.get("has_more_page", False):
                        break
                    page += 1

                    if page > 50:
                        break

        except Exception as e:
            logger.error(f"Failed to fetch Zoho Books records: {e}")
            return []

        # Group records by date
        date_groups: dict[date, list[dict]] = defaultdict(list)
        for record in all_records:
            raw_date = record.get(date_field, "")
            if not raw_date:
                continue

            record_date = None
            if isinstance(raw_date, str):
                try:
                    record_date = datetime.strptime(raw_date[:10], ZOHO_DATE_FORMAT).date()
                except ValueError:
                    continue

            if record_date:
                date_groups[record_date].append(record)

        # Aggregate by date
        rows = []
        for record_date, records in sorted(date_groups.items()):
            entry = {"date": record_date, "_records": records, "_count": len(records)}

            numeric_sums: dict[str, float] = defaultdict(float)
            numeric_counts: dict[str, int] = defaultdict(int)

            for rec in records:
                for key, val in rec.items():
                    if key.startswith("_") or isinstance(val, (dict, list)):
                        continue
                    if isinstance(val, (int, float)):
                        numeric_sums[key] += val
                        numeric_counts[key] += 1

            for field_name in numeric_sums:
                entry[f"{field_name}__sum"] = numeric_sums[field_name]
                entry[f"{field_name}__count"] = numeric_counts[field_name]
                entry[f"{field_name}__avg"] = (
                    numeric_sums[field_name] / numeric_counts[field_name]
                    if numeric_counts[field_name] > 0
                    else 0
                )

            entry["__record_count"] = len(records)
            rows.append(entry)

        return rows
