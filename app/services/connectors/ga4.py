"""Google Analytics 4 connector via the GA4 Data API (Data API v1beta).

Auth: OAuth2 (scope: analytics.readonly).

Config fields:
  - property_id: numeric GA4 property ID (e.g. "123456789"); the "properties/"
    prefix is optional and stripped.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app.core.config import settings
from app.core.encryption import encrypt_value, decrypt_value
from app.services.connectors.base import BaseConnector, ExternalField

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GA4_API_BASE = "https://analyticsdata.googleapis.com/v1beta"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

# (GA4 API metric name, label, type, output key)
GA4_METRICS = [
    ("sessions", "Sessions", "number", "sessions"),
    ("activeUsers", "Active Users", "number", "active_users"),
    ("newUsers", "New Users", "number", "new_users"),
    ("totalUsers", "Total Users", "number", "total_users"),
    ("screenPageViews", "Page Views", "number", "page_views"),
    ("bounceRate", "Bounce Rate", "number", "bounce_rate"),
    ("engagementRate", "Engagement Rate", "number", "engagement_rate"),
    ("averageSessionDuration", "Avg. Session Duration (s)", "number", "avg_session_duration"),
    ("userEngagementDuration", "User Engagement Duration (s)", "number", "user_engagement_duration"),
    ("eventCount", "Event Count", "number", "event_count"),
    ("conversions", "Conversions", "number", "conversions"),
    ("totalRevenue", "Total Revenue", "number", "total_revenue"),
    ("purchaseRevenue", "Purchase Revenue", "number", "purchase_revenue"),
    ("transactions", "Transactions", "number", "transactions"),
]


def _normalize_property_id(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("properties/"):
        raw = raw.replace("properties/", "", 1)
    return raw


class GA4Connector(BaseConnector):
    """Connector for Google Analytics 4 via the Data API."""

    # --- OAuth helpers (static) ---

    @staticmethod
    def get_authorize_url(state: str) -> str:
        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID or "",
            "redirect_uri": settings.GA4_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        query = "&".join(f"{k}={httpx.URL('', params={k: v}).params[k]}" for k, v in params.items())
        return f"{GOOGLE_AUTH_URI}?{query}"

    @staticmethod
    def exchange_code(code: str) -> dict:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                GOOGLE_TOKEN_URI,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_OAUTH_CLIENT_ID or "",
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET or "",
                    "redirect_uri": settings.GA4_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    # --- Instance methods ---

    def _access_token(self) -> str:
        return decrypt_value(self.integration.access_token_encrypted) if self.integration.access_token_encrypted else ""

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
        }

    def _property_id(self) -> str:
        return _normalize_property_id(str((self.integration.config or {}).get("property_id", "")))

    def refresh_auth(self) -> bool:
        refresh_token = decrypt_value(self.integration.refresh_token_encrypted) if self.integration.refresh_token_encrypted else None
        if not refresh_token:
            return False
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.post(
                    GOOGLE_TOKEN_URI,
                    data={
                        "refresh_token": refresh_token,
                        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID or "",
                        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET or "",
                        "grant_type": "refresh_token",
                    },
                )
                resp.raise_for_status()
                tokens = resp.json()
            if "access_token" not in tokens:
                return False
            if self.db and self.integration:
                self.integration.access_token_encrypted = encrypt_value(tokens["access_token"])
                expires_in = tokens.get("expires_in", 3600)
                self.integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                self.db.commit()
            return True
        except Exception as e:
            logger.error(f"GA4 token refresh failed: {e}")
            return False

    def test_connection(self) -> bool:
        pid = self._property_id()
        if not pid:
            return False
        try:
            body = {
                "dateRanges": [{"startDate": "yesterday", "endDate": "today"}],
                "metrics": [{"name": "sessions"}],
                "limit": 1,
            }
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{GA4_API_BASE}/properties/{pid}:runReport",
                    headers=self._headers(),
                    json=body,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"GA4 test connection failed: {e}")
            return False

    def get_available_fields(self) -> list[ExternalField]:
        return [ExternalField(name=key, label=label, field_type=ftype) for (_api, label, ftype, key) in GA4_METRICS]

    def fetch_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        pid = self._property_id()
        if not pid:
            logger.error("GA4: no property_id configured")
            return []

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        body = {
            "dateRanges": [{
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
            }],
            "dimensions": [{"name": "date"}],
            "metrics": [{"name": api_name} for (api_name, _l, _t, _k) in GA4_METRICS],
            "orderBys": [{"dimension": {"dimensionName": "date"}}],
            "limit": 100000,
        }

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{GA4_API_BASE}/properties/{pid}:runReport",
                    headers=self._headers(),
                    json=body,
                )
                if resp.status_code != 200:
                    logger.error(f"GA4 runReport error {resp.status_code}: {resp.text[:500]}")
                    return []
                data = resp.json()
        except Exception as e:
            logger.error(f"GA4 fetch failed: {e}")
            return []

        rows_out: list[dict] = []
        for row in data.get("rows") or []:
            dim_values = row.get("dimensionValues") or []
            metric_values = row.get("metricValues") or []
            if not dim_values:
                continue
            dstr = dim_values[0].get("value", "")
            try:
                d = datetime.strptime(dstr, "%Y%m%d").date()
            except ValueError:
                continue

            entry: dict = {"date": d}
            for i, (_api, _label, _type, key) in enumerate(GA4_METRICS):
                if i < len(metric_values):
                    raw = metric_values[i].get("value", "0")
                    try:
                        entry[key] = float(raw)
                    except (TypeError, ValueError):
                        entry[key] = 0.0
                else:
                    entry[key] = 0.0
            rows_out.append(entry)

        return rows_out
