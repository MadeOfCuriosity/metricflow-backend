import logging
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app.core.config import settings
from app.core.encryption import encrypt_value, decrypt_value
from app.services.connectors.base import BaseConnector, ExternalField

logger = logging.getLogger(__name__)

ZOHO_AUTH_URI = "https://accounts.zoho.com/oauth/v2/auth"
ZOHO_TOKEN_URI = "https://accounts.zoho.com/oauth/v2/token"
ZOHO_SHEET_API_BASE = "https://sheet.zoho.com/api/v2"
ZOHO_SHEET_SCOPES = "ZohoSheet.dataAPI.READ"

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]


class ZohoSheetConnector(BaseConnector):
    """Connector for Zoho Sheet API v2."""

    @staticmethod
    def get_authorize_url(state: str) -> str:
        """Generate OAuth2 authorization URL for Zoho Sheet."""
        params = {
            "scope": ZOHO_SHEET_SCOPES,
            "client_id": settings.ZOHO_OAUTH_CLIENT_ID,
            "response_type": "code",
            "access_type": "offline",
            "redirect_uri": settings.ZOHO_SHEET_OAUTH_REDIRECT_URI,
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
                    "redirect_uri": settings.ZOHO_SHEET_OAUTH_REDIRECT_URI,
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

    def _get_resource_id(self) -> str:
        """Get the Zoho Sheet resource ID from config."""
        config = self.integration.config or {}
        return config.get("resource_id", "")

    def _get_sheet_name(self) -> str:
        """Get the sheet/worksheet name from config."""
        config = self.integration.config or {}
        return config.get("sheet_name", "Sheet1")

    def test_connection(self) -> bool:
        """Test connection by fetching workbook info."""
        resource_id = self._get_resource_id()
        if not resource_id:
            return False
        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{ZOHO_SHEET_API_BASE}/{resource_id}",
                    headers=self._get_headers(),
                    params={"method": "worksheet.list"},
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Zoho Sheet connection test failed: {e}")
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
                logger.error(f"Zoho Sheet refresh failed: {tokens}")
                return False

            if self.db and self.integration:
                self.integration.access_token_encrypted = encrypt_value(tokens["access_token"])
                expires_in = tokens.get("expires_in", 3600)
                self.integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                self.db.commit()

            return True
        except Exception as e:
            logger.error(f"Zoho Sheet token refresh failed: {e}")
            return False

    def get_available_fields(self) -> list[ExternalField]:
        """Fetch the header row to discover available columns."""
        resource_id = self._get_resource_id()
        sheet_name = self._get_sheet_name()

        try:
            with httpx.Client() as client:
                resp = client.get(
                    f"{ZOHO_SHEET_API_BASE}/{resource_id}",
                    headers=self._get_headers(),
                    params={
                        "method": "worksheet.records.fetch",
                        "worksheet_name": sheet_name,
                        "header_row": 1,
                        "start_row": 2,
                        "row_count": 1,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

            records = data.get("records", [])
            if not records:
                return []

            sample = records[0]
            fields = []
            for key in sample.keys():
                if key.startswith("row_"):
                    continue
                field_type = "string"
                val = sample[key]
                if isinstance(val, (int, float)):
                    field_type = "number"
                fields.append(ExternalField(
                    name=key,
                    label=key,
                    field_type=field_type,
                ))
            return fields

        except Exception as e:
            logger.error(f"Failed to fetch Zoho Sheet fields: {e}")
            return []

    def _parse_date(self, value: str) -> Optional[date]:
        """Try to parse a date string using multiple formats."""
        if not value or not isinstance(value, str):
            return None
        value = value.strip()
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        # Try ISO format
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            return None

    def fetch_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Fetch all rows from the Zoho Sheet, parse dates, and return
        rows as dicts with a "date" key.
        """
        resource_id = self._get_resource_id()
        sheet_name = self._get_sheet_name()
        config = self.integration.config or {}
        date_column = config.get("date_column", "Date")

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        all_rows = []
        start_row = 2  # Skip header
        batch_size = 500

        try:
            with httpx.Client(timeout=30) as client:
                while True:
                    resp = client.get(
                        f"{ZOHO_SHEET_API_BASE}/{resource_id}",
                        headers=self._get_headers(),
                        params={
                            "method": "worksheet.records.fetch",
                            "worksheet_name": sheet_name,
                            "header_row": 1,
                            "start_row": start_row,
                            "row_count": batch_size,
                        },
                    )

                    if resp.status_code == 204:
                        break
                    resp.raise_for_status()
                    data = resp.json()

                    records = data.get("records", [])
                    if not records:
                        break

                    all_rows.extend(records)
                    start_row += batch_size

                    if len(records) < batch_size:
                        break
                    if start_row > 10000:
                        break

        except Exception as e:
            logger.error(f"Failed to fetch Zoho Sheet data: {e}")
            return []

        # Process rows: parse dates, convert numeric values
        result = []
        for row in all_rows:
            raw_date = row.get(date_column, "")
            row_date = self._parse_date(str(raw_date))

            if not row_date:
                continue
            if row_date < start_date or row_date > end_date:
                continue

            entry = {"date": row_date}
            for key, val in row.items():
                if key == date_column or key.startswith("row_"):
                    continue
                # Try to parse as number
                if isinstance(val, (int, float)):
                    entry[key] = val
                elif isinstance(val, str):
                    cleaned = val.strip().replace(",", "")
                    try:
                        entry[key] = float(cleaned)
                    except ValueError:
                        entry[key] = val

            result.append(entry)

        return result
