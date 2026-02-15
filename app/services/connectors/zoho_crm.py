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
ZOHO_API_BASE = "https://www.zohoapis.com/crm/v6"
ZOHO_SCOPES = "ZohoCRM.modules.ALL,ZohoCRM.settings.ALL"

# Zoho date format
ZOHO_DATE_FORMAT = "%Y-%m-%d"


class ZohoCRMConnector(BaseConnector):
    """Connector for Zoho CRM API v6."""

    @staticmethod
    def get_authorize_url(state: str) -> str:
        """Generate OAuth2 authorization URL for Zoho."""
        params = {
            "scope": ZOHO_SCOPES,
            "client_id": settings.ZOHO_OAUTH_CLIENT_ID,
            "response_type": "code",
            "access_type": "offline",
            "redirect_uri": settings.ZOHO_OAUTH_REDIRECT_URI,
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
                    "redirect_uri": settings.ZOHO_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    def _get_headers(self) -> dict:
        """Get authorization headers with the current access token."""
        access_token = decrypt_value(self.integration.access_token_encrypted) if self.integration.access_token_encrypted else ""
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        }

    def test_connection(self) -> bool:
        """Test connection by fetching org info from Zoho."""
        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{ZOHO_API_BASE}/org",
                    headers=self._get_headers(),
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Zoho CRM connection test failed: {e}")
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
                logger.error(f"Zoho refresh failed: {tokens}")
                return False

            if self.db and self.integration:
                self.integration.access_token_encrypted = encrypt_value(tokens["access_token"])
                expires_in = tokens.get("expires_in", 3600)
                self.integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                self.db.commit()

            return True
        except Exception as e:
            logger.error(f"Zoho CRM token refresh failed: {e}")
            return False

    def get_available_fields(self) -> list[ExternalField]:
        """Fetch field metadata for the configured CRM module."""
        config = self.integration.config or {}
        module = config.get("module", "Deals")

        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{ZOHO_API_BASE}/settings/fields",
                    headers=self._get_headers(),
                    params={"module": module},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

            fields = []
            for f in data.get("fields", []):
                field_type = "string"
                zoho_type = f.get("data_type", "").lower()
                if zoho_type in ("integer", "double", "currency", "bigint", "decimal"):
                    field_type = "number"
                elif zoho_type in ("date", "datetime"):
                    field_type = "date"
                elif zoho_type == "boolean":
                    field_type = "boolean"

                fields.append(ExternalField(
                    name=f.get("api_name", ""),
                    label=f.get("display_label", f.get("api_name", "")),
                    field_type=field_type,
                ))
            return fields
        except Exception as e:
            logger.error(f"Failed to fetch Zoho CRM fields: {e}")
            return []

    def fetch_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Fetch records from the configured Zoho module, aggregate by date.
        Returns list of dicts with "date" key and aggregated values.
        """
        config = self.integration.config or {}
        module = config.get("module", "Deals")
        date_field = config.get("date_field", "Created_Time")

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        all_records = []
        page = 1
        per_page = 200

        try:
            with httpx.Client(timeout=30) as client:
                while True:
                    # Build criteria filter for date range
                    criteria = f"(({date_field}:greater_equal:{start_date.strftime(ZOHO_DATE_FORMAT)})and({date_field}:less_equal:{end_date.strftime(ZOHO_DATE_FORMAT)}))"

                    resp = client.get(
                        f"{ZOHO_API_BASE}/{module}/search",
                        headers=self._get_headers(),
                        params={
                            "criteria": criteria,
                            "page": page,
                            "per_page": per_page,
                        },
                    )

                    if resp.status_code == 204:
                        break  # No records
                    resp.raise_for_status()
                    data = resp.json()

                    records = data.get("data", [])
                    all_records.extend(records)

                    info = data.get("info", {})
                    if not info.get("more_records", False):
                        break
                    page += 1

                    # Safety limit
                    if page > 50:
                        break

        except Exception as e:
            logger.error(f"Failed to fetch Zoho CRM records: {e}")
            return []

        # Group records by date and extract field values
        date_groups: dict[date, list[dict]] = defaultdict(list)
        for record in all_records:
            raw_date = record.get(date_field, "")
            if not raw_date:
                continue

            # Zoho dates can be "2024-01-15" or "2024-01-15T10:30:00+05:30"
            record_date = None
            if isinstance(raw_date, str):
                try:
                    record_date = datetime.strptime(raw_date[:10], ZOHO_DATE_FORMAT).date()
                except ValueError:
                    continue

            if record_date:
                date_groups[record_date].append(record)

        # Aggregate by date — the actual aggregation is applied per-mapping in SyncService
        # Here we return per-record data grouped by date for flexible aggregation
        rows = []
        for record_date, records in sorted(date_groups.items()):
            entry = {"date": record_date, "_records": records, "_count": len(records)}

            # Pre-compute common aggregations for numeric fields
            numeric_sums: dict[str, float] = defaultdict(float)
            numeric_counts: dict[str, int] = defaultdict(int)

            for rec in records:
                for key, val in rec.items():
                    if key.startswith("$") or key == date_field:
                        continue
                    if isinstance(val, (int, float)):
                        numeric_sums[key] += val
                        numeric_counts[key] += 1

            # Store per-field aggregated values
            for field_name in numeric_sums:
                entry[f"{field_name}__sum"] = numeric_sums[field_name]
                entry[f"{field_name}__count"] = numeric_counts[field_name]
                entry[f"{field_name}__avg"] = (
                    numeric_sums[field_name] / numeric_counts[field_name]
                    if numeric_counts[field_name] > 0
                    else 0
                )

            # Also store total record count for "count" aggregation
            entry["__record_count"] = len(records)
            rows.append(entry)

        return rows
