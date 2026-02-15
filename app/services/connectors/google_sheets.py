import logging
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings
from app.core.encryption import encrypt_value, decrypt_value
from app.services.connectors.base import BaseConnector, ExternalField

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"

# Common date formats to try when parsing
DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
]


def parse_date(value: str) -> Optional[date]:
    """Try to parse a date string using multiple formats."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_number(value) -> Optional[float]:
    """Parse a value as a number, handling common formats."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "").replace("%", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


class GoogleSheetsConnector(BaseConnector):
    """Connector for Google Sheets via Google Sheets API v4."""

    @staticmethod
    def get_authorize_url(state: str) -> str:
        """Generate OAuth2 authorization URL for Google."""
        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        query = "&".join(f"{k}={httpx.URL('', params={k: v}).params[k]}" for k, v in params.items())
        return f"{GOOGLE_AUTH_URI}?{query}"

    @staticmethod
    def exchange_code(code: str) -> dict:
        """Exchange authorization code for access + refresh tokens."""
        with httpx.Client() as client:
            resp = client.post(
                GOOGLE_TOKEN_URI,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    def _get_credentials(self) -> Credentials:
        """Build Google Credentials from stored encrypted tokens."""
        access_token = decrypt_value(self.integration.access_token_encrypted) if self.integration.access_token_encrypted else None
        refresh_token = decrypt_value(self.integration.refresh_token_encrypted) if self.integration.refresh_token_encrypted else None

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            scopes=SCOPES,
        )
        return creds

    def _get_service(self):
        """Build the Google Sheets API service."""
        creds = self._get_credentials()
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    def test_connection(self) -> bool:
        """Test connection by reading spreadsheet metadata."""
        try:
            service = self._get_service()
            spreadsheet_id = self.integration.config.get("spreadsheet_id", "")
            if not spreadsheet_id:
                return False
            service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            return True
        except Exception as e:
            logger.error(f"Google Sheets connection test failed: {e}")
            return False

    def refresh_auth(self) -> bool:
        """Refresh the OAuth access token using the refresh token."""
        refresh_token = decrypt_value(self.integration.refresh_token_encrypted) if self.integration.refresh_token_encrypted else None
        if not refresh_token:
            return False

        try:
            with httpx.Client() as client:
                resp = client.post(
                    GOOGLE_TOKEN_URI,
                    data={
                        "refresh_token": refresh_token,
                        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                        "grant_type": "refresh_token",
                    },
                )
                resp.raise_for_status()
                tokens = resp.json()

            # Update stored tokens
            if self.db and self.integration:
                self.integration.access_token_encrypted = encrypt_value(tokens["access_token"])
                if "refresh_token" in tokens:
                    self.integration.refresh_token_encrypted = encrypt_value(tokens["refresh_token"])
                expires_in = tokens.get("expires_in", 3600)
                self.integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                self.db.commit()

            return True
        except Exception as e:
            logger.error(f"Google Sheets token refresh failed: {e}")
            return False

    def get_available_fields(self) -> list[ExternalField]:
        """Read header row from the configured sheet to get column names."""
        config = self.integration.config or {}
        spreadsheet_id = config.get("spreadsheet_id", "")
        sheet_name = config.get("sheet_name", "Sheet1")
        header_row = config.get("header_row", 1)

        if not spreadsheet_id:
            return []

        try:
            service = self._get_service()
            range_str = f"'{sheet_name}'!{header_row}:{header_row}"
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_str,
            ).execute()

            values = result.get("values", [[]])
            headers = values[0] if values else []

            fields = []
            for i, header in enumerate(headers):
                header = str(header).strip()
                if header:
                    fields.append(ExternalField(
                        name=header,
                        label=header,
                        field_type="string",  # Sheets doesn't expose column types via API
                    ))
            return fields
        except HttpError as e:
            logger.error(f"Failed to read Google Sheets headers: {e}")
            return []

    def fetch_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Fetch rows from the sheet. Each row is returned as a dict with
        a "date" key parsed from the configured date column, plus all other
        column values keyed by header name.
        """
        config = self.integration.config or {}
        spreadsheet_id = config.get("spreadsheet_id", "")
        sheet_name = config.get("sheet_name", "Sheet1")
        date_column = config.get("date_column", "")
        header_row = config.get("header_row", 1)

        if not spreadsheet_id:
            return []

        try:
            service = self._get_service()

            # Read all data starting from header row
            data_start = header_row + 1
            range_str = f"'{sheet_name}'!{header_row}:10000"
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_str,
            ).execute()

            all_rows = result.get("values", [])
            if len(all_rows) < 2:
                return []

            headers = [str(h).strip() for h in all_rows[0]]
            data_rows = all_rows[1:]

            # Find date column index
            date_col_idx = None
            if date_column:
                for i, h in enumerate(headers):
                    if h.lower() == date_column.lower():
                        date_col_idx = i
                        break

            rows = []
            for row in data_rows:
                # Pad row to match headers length
                padded = row + [""] * (len(headers) - len(row))

                # Parse date
                row_date = None
                if date_col_idx is not None and date_col_idx < len(padded):
                    row_date = parse_date(padded[date_col_idx])

                if row_date is None:
                    continue  # Skip rows without a parseable date

                # Apply date filters
                if start_date and row_date < start_date:
                    continue
                if end_date and row_date > end_date:
                    continue

                entry = {"date": row_date}
                for i, header in enumerate(headers):
                    if i != date_col_idx and header:
                        entry[header] = parse_number(padded[i])
                rows.append(entry)

            return rows
        except HttpError as e:
            logger.error(f"Failed to fetch Google Sheets data: {e}")
            return []
