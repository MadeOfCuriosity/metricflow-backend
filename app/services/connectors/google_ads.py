"""Google Ads connector — pulls daily campaign metrics via Google Ads REST API.

Auth: OAuth2 (scope: adwords) + a developer token (env) required by Google Ads API.
Config fields on the integration:
  - customer_id: Google Ads customer ID (10 digits, dashes ignored, e.g. "123-456-7890")
  - login_customer_id: optional MCC manager ID if the above is accessed via a manager
  - campaign_name_contains: optional case-insensitive substring filter
"""
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app.core.config import settings
from app.core.encryption import encrypt_value, decrypt_value
from app.services.connectors.base import BaseConnector, ExternalField

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_ADS_API_VERSION = "v17"
GOOGLE_ADS_API_BASE = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"
SCOPES = ["https://www.googleapis.com/auth/adwords"]


# The metrics we expose as mappable fields. Keys match what fetch_data returns.
GOOGLE_ADS_FIELDS = [
    ("impressions", "Impressions", "number"),
    ("clicks", "Clicks", "number"),
    ("cost", "Cost (Spend)", "number"),
    ("conversions", "Conversions", "number"),
    ("conversions_value", "Conversions Value (Revenue)", "number"),
    ("all_conversions", "All Conversions", "number"),
    ("ctr", "CTR (click-through rate)", "number"),
    ("avg_cpc", "Avg. CPC", "number"),
    ("cpm", "Avg. CPM", "number"),
    ("cpa", "CPA (Cost per Acquisition)", "number"),
    ("roas", "ROAS (Return on Ad Spend)", "number"),
    ("search_impression_share", "Search Impression Share", "number"),
]


def _normalize_customer_id(cid: str) -> str:
    return (cid or "").replace("-", "").replace(" ", "").strip()


class GoogleAdsConnector(BaseConnector):
    """Connector for Google Ads API via GAQL over REST."""

    # --- OAuth helpers (static, used by routes) ---

    @staticmethod
    def get_authorize_url(state: str) -> str:
        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID or "",
            "redirect_uri": settings.GOOGLE_ADS_OAUTH_REDIRECT_URI,
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
                    "redirect_uri": settings.GOOGLE_ADS_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    # --- Instance methods ---

    def _access_token(self) -> str:
        return decrypt_value(self.integration.access_token_encrypted) if self.integration.access_token_encrypted else ""

    def _headers(self) -> dict:
        if not settings.GOOGLE_ADS_DEVELOPER_TOKEN:
            raise RuntimeError("GOOGLE_ADS_DEVELOPER_TOKEN is not configured")
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
            "Content-Type": "application/json",
        }
        login_cid = (self.integration.config or {}).get("login_customer_id")
        if login_cid:
            headers["login-customer-id"] = _normalize_customer_id(str(login_cid))
        return headers

    def _customer_id(self) -> str:
        cid = (self.integration.config or {}).get("customer_id", "")
        return _normalize_customer_id(str(cid))

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
            logger.error(f"Google Ads token refresh failed: {e}")
            return False

    def test_connection(self) -> bool:
        cid = self._customer_id()
        if not cid:
            return False
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{GOOGLE_ADS_API_BASE}/customers/{cid}/googleAds:search",
                    headers=self._headers(),
                    json={"query": "SELECT customer.id FROM customer LIMIT 1"},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Google Ads test connection failed: {e}")
            return False

    def get_available_fields(self) -> list[ExternalField]:
        return [ExternalField(name=n, label=l, field_type=t) for (n, l, t) in GOOGLE_ADS_FIELDS]

    def fetch_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        cid = self._customer_id()
        if not cid:
            logger.error("Google Ads: no customer_id configured")
            return []

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        # Substring filter on campaign name (applied client-side)
        name_filter = ((self.integration.config or {}).get("campaign_name_contains") or "").strip().lower()

        gaql = f"""
            SELECT
                segments.date,
                campaign.id,
                campaign.name,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value,
                metrics.all_conversions,
                metrics.ctr,
                metrics.average_cpc,
                metrics.average_cpm,
                metrics.search_impression_share
            FROM campaign
            WHERE segments.date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        """.strip()

        rows_raw = []
        try:
            with httpx.Client(timeout=60) as client:
                # searchStream returns chunked results; use search with pagination for simplicity
                page_token = None
                while True:
                    body = {"query": gaql, "pageSize": 10000}
                    if page_token:
                        body["pageToken"] = page_token
                    resp = client.post(
                        f"{GOOGLE_ADS_API_BASE}/customers/{cid}/googleAds:search",
                        headers=self._headers(),
                        json=body,
                    )
                    if resp.status_code != 200:
                        logger.error(f"Google Ads API error {resp.status_code}: {resp.text[:500]}")
                        return []
                    data = resp.json()
                    rows_raw.extend(data.get("results") or [])
                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break
        except Exception as e:
            logger.error(f"Google Ads fetch failed: {e}")
            return []

        # Aggregate per-date across campaigns
        daily: dict[date, dict[str, float]] = defaultdict(lambda: {
            "impressions": 0.0, "clicks": 0.0, "cost": 0.0,
            "conversions": 0.0, "conversions_value": 0.0, "all_conversions": 0.0,
            "_sis_sum": 0.0, "_sis_n": 0.0,
        })

        for row in rows_raw:
            segments = row.get("segments") or {}
            campaign = row.get("campaign") or {}
            metrics = row.get("metrics") or {}

            dstr = segments.get("date")
            if not dstr:
                continue

            if name_filter:
                cname = (campaign.get("name") or "").lower()
                if name_filter not in cname:
                    continue

            try:
                d = datetime.strptime(dstr, "%Y-%m-%d").date()
            except ValueError:
                continue

            bucket = daily[d]
            bucket["impressions"] += float(metrics.get("impressions") or 0)
            bucket["clicks"] += float(metrics.get("clicks") or 0)
            bucket["cost"] += float(metrics.get("costMicros") or 0) / 1_000_000.0
            bucket["conversions"] += float(metrics.get("conversions") or 0)
            bucket["conversions_value"] += float(metrics.get("conversionsValue") or 0)
            bucket["all_conversions"] += float(metrics.get("allConversions") or 0)

            sis = metrics.get("searchImpressionShare")
            if isinstance(sis, (int, float)):
                bucket["_sis_sum"] += float(sis)
                bucket["_sis_n"] += 1

        results: list[dict] = []
        for d, b in sorted(daily.items()):
            impressions = b["impressions"]
            clicks = b["clicks"]
            cost = b["cost"]
            conv = b["conversions"]
            conv_val = b["conversions_value"]

            entry = {
                "date": d,
                "impressions": impressions,
                "clicks": clicks,
                "cost": round(cost, 4),
                "conversions": conv,
                "conversions_value": round(conv_val, 4),
                "all_conversions": b["all_conversions"],
                "ctr": (clicks / impressions) if impressions > 0 else 0.0,
                "avg_cpc": (cost / clicks) if clicks > 0 else 0.0,
                "cpm": (cost / impressions * 1000.0) if impressions > 0 else 0.0,
                "cpa": (cost / conv) if conv > 0 else 0.0,
                "roas": (conv_val / cost) if cost > 0 else 0.0,
                "search_impression_share": (b["_sis_sum"] / b["_sis_n"]) if b["_sis_n"] > 0 else 0.0,
            }
            results.append(entry)

        return results
