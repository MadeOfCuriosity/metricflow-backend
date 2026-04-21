"""Meta (Facebook + Instagram) Ads connector via the Marketing API.

Auth: OAuth2 (scopes: ads_read, business_management).
Facebook doesn't issue refresh tokens — instead we exchange short-lived
for long-lived user tokens (~60 days) via fb_exchange_token, and re-exchange
during refresh_auth to extend validity.

Config fields:
  - ad_account_id: "act_1234567890" (the `act_` prefix is optional; we add it)
  - campaign_name_contains: optional client-side filter substring
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

META_AUTH_URI = "https://www.facebook.com/{v}/dialog/oauth"
META_TOKEN_URI = "https://graph.facebook.com/{v}/oauth/access_token"
META_GRAPH_BASE = "https://graph.facebook.com/{v}"

META_SCOPES = "ads_read,business_management"

# Fields exposed for mapping. Keys align with fetch_data output.
META_ADS_FIELDS = [
    ("spend", "Spend", "number"),
    ("impressions", "Impressions", "number"),
    ("reach", "Reach", "number"),
    ("frequency", "Frequency", "number"),
    ("clicks", "Clicks", "number"),
    ("unique_clicks", "Unique Clicks", "number"),
    ("ctr", "CTR", "number"),
    ("cpc", "CPC", "number"),
    ("cpm", "CPM", "number"),
    ("cpp", "CPP", "number"),
    ("purchases", "Purchases (conversions)", "number"),
    ("leads", "Leads", "number"),
    ("link_clicks", "Link Clicks", "number"),
    ("landing_page_views", "Landing Page Views", "number"),
    ("purchase_value", "Purchase Value (Revenue)", "number"),
    ("roas", "ROAS (Purchase Value / Spend)", "number"),
    ("cpa", "CPA (Spend / Purchases)", "number"),
]


def _v() -> str:
    return settings.META_API_VERSION or "v19.0"


def _auth_uri() -> str:
    return META_AUTH_URI.format(v=_v())


def _token_uri() -> str:
    return META_TOKEN_URI.format(v=_v())


def _graph_base() -> str:
    return META_GRAPH_BASE.format(v=_v())


def _normalize_ad_account_id(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not raw.startswith("act_"):
        raw = f"act_{raw}"
    return raw


class MetaAdsConnector(BaseConnector):
    """Connector for Meta (Facebook + Instagram) Ads via Graph API."""

    # --- OAuth helpers (static) ---

    @staticmethod
    def get_authorize_url(state: str) -> str:
        params = {
            "client_id": settings.META_OAUTH_CLIENT_ID or "",
            "redirect_uri": settings.META_OAUTH_REDIRECT_URI,
            "state": state,
            "scope": META_SCOPES,
            "response_type": "code",
        }
        query = "&".join(f"{k}={httpx.URL('', params={k: v}).params[k]}" for k, v in params.items())
        return f"{_auth_uri()}?{query}"

    @staticmethod
    def exchange_code(code: str) -> dict:
        """Exchange auth code for short-lived access token, then immediately
        exchange for a long-lived (~60 day) token."""
        with httpx.Client(timeout=20) as client:
            # Step 1: authorization code → short-lived access token
            resp = client.get(
                _token_uri(),
                params={
                    "client_id": settings.META_OAUTH_CLIENT_ID or "",
                    "client_secret": settings.META_OAUTH_CLIENT_SECRET or "",
                    "redirect_uri": settings.META_OAUTH_REDIRECT_URI,
                    "code": code,
                },
            )
            resp.raise_for_status()
            short = resp.json()
            short_token = short.get("access_token", "")

            # Step 2: short-lived → long-lived (~60 days)
            resp = client.get(
                _token_uri(),
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.META_OAUTH_CLIENT_ID or "",
                    "client_secret": settings.META_OAUTH_CLIENT_SECRET or "",
                    "fb_exchange_token": short_token,
                },
            )
            resp.raise_for_status()
            long_lived = resp.json()

            return {
                "access_token": long_lived.get("access_token", short_token),
                # Meta returns expires_in in seconds (~5184000 for 60 days)
                "expires_in": long_lived.get("expires_in", 5_184_000),
                "refresh_token": None,
            }

    # --- Instance methods ---

    def _access_token(self) -> str:
        return decrypt_value(self.integration.access_token_encrypted) if self.integration.access_token_encrypted else ""

    def _ad_account_id(self) -> str:
        return _normalize_ad_account_id(str((self.integration.config or {}).get("ad_account_id", "")))

    def refresh_auth(self) -> bool:
        """Extend the long-lived token by re-exchanging via fb_exchange_token.
        No true refresh token exists for Meta user tokens."""
        token = self._access_token()
        if not token:
            return False
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.get(
                    _token_uri(),
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": settings.META_OAUTH_CLIENT_ID or "",
                        "client_secret": settings.META_OAUTH_CLIENT_SECRET or "",
                        "fb_exchange_token": token,
                    },
                )
            if resp.status_code != 200:
                # If token is still valid we can proceed, otherwise fail
                logger.warning(f"Meta token refresh non-200 ({resp.status_code}); falling back to existing token")
                return bool(token)
            data = resp.json()
            new_token = data.get("access_token")
            if not new_token:
                return bool(token)

            if self.db and self.integration:
                self.integration.access_token_encrypted = encrypt_value(new_token)
                expires_in = data.get("expires_in", 5_184_000)
                self.integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                self.db.commit()
            return True
        except Exception as e:
            logger.error(f"Meta token refresh failed: {e}")
            return bool(token)

    def test_connection(self) -> bool:
        acct = self._ad_account_id()
        if not acct:
            return False
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"{_graph_base()}/{acct}",
                    params={"fields": "id,name,currency", "access_token": self._access_token()},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Meta Ads test connection failed: {e}")
            return False

    def get_available_fields(self) -> list[ExternalField]:
        return [ExternalField(name=n, label=l, field_type=t) for (n, l, t) in META_ADS_FIELDS]

    def fetch_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        acct = self._ad_account_id()
        if not acct:
            logger.error("Meta Ads: no ad_account_id configured")
            return []

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        # Aggregate at campaign level so we can apply the name filter; then roll up by date.
        name_filter = ((self.integration.config or {}).get("campaign_name_contains") or "").strip().lower()

        fields = ",".join([
            "campaign_name", "spend", "impressions", "reach", "frequency",
            "clicks", "unique_clicks", "ctr", "cpc", "cpm", "cpp",
            "actions", "action_values",
        ])
        params = {
            "access_token": self._access_token(),
            "level": "campaign",
            "fields": fields,
            "time_range": f'{{"since":"{start_date.isoformat()}","until":"{end_date.isoformat()}"}}',
            "time_increment": 1,
            "limit": 500,
        }

        rows: list[dict] = []
        url = f"{_graph_base()}/{acct}/insights"
        try:
            with httpx.Client(timeout=60) as client:
                while url:
                    resp = client.get(url, params=params if url.endswith("/insights") else None)
                    if resp.status_code != 200:
                        logger.error(f"Meta insights error {resp.status_code}: {resp.text[:500]}")
                        return []
                    data = resp.json()
                    rows.extend(data.get("data") or [])
                    # Paging via `paging.next` (a fully-qualified URL)
                    paging = data.get("paging") or {}
                    url = paging.get("next")
                    params = None  # After first page, params are embedded in `next`
        except Exception as e:
            logger.error(f"Meta Ads fetch failed: {e}")
            return []

        # Helper: sum matching action types
        def _sum_actions(actions: list[dict] | None, needles: tuple[str, ...]) -> float:
            total = 0.0
            if not isinstance(actions, list):
                return total
            for a in actions:
                at = str(a.get("action_type", ""))
                if any(n in at for n in needles):
                    try:
                        total += float(a.get("value") or 0)
                    except (TypeError, ValueError):
                        pass
            return total

        # Aggregate by date
        daily: dict[date, dict[str, float]] = defaultdict(lambda: {
            "spend": 0.0, "impressions": 0.0, "reach": 0.0, "frequency_sum": 0.0, "frequency_n": 0.0,
            "clicks": 0.0, "unique_clicks": 0.0,
            "purchases": 0.0, "leads": 0.0, "link_clicks": 0.0, "landing_page_views": 0.0,
            "purchase_value": 0.0,
        })

        for r in rows:
            if name_filter:
                cname = str(r.get("campaign_name") or "").lower()
                if name_filter not in cname:
                    continue

            dstr = r.get("date_start") or r.get("date_stop")
            if not dstr:
                continue
            try:
                d = datetime.strptime(dstr, "%Y-%m-%d").date()
            except ValueError:
                continue

            def _f(key: str) -> float:
                try:
                    return float(r.get(key) or 0)
                except (TypeError, ValueError):
                    return 0.0

            b = daily[d]
            b["spend"] += _f("spend")
            b["impressions"] += _f("impressions")
            b["reach"] += _f("reach")
            b["clicks"] += _f("clicks")
            b["unique_clicks"] += _f("unique_clicks")
            freq = _f("frequency")
            if freq > 0:
                b["frequency_sum"] += freq
                b["frequency_n"] += 1

            actions = r.get("actions")
            action_values = r.get("action_values")

            b["purchases"] += _sum_actions(actions, ("purchase",))
            b["leads"] += _sum_actions(actions, ("lead",))
            b["link_clicks"] += _sum_actions(actions, ("link_click",))
            b["landing_page_views"] += _sum_actions(actions, ("landing_page_view",))
            b["purchase_value"] += _sum_actions(action_values, ("purchase",))

        results: list[dict] = []
        for d, b in sorted(daily.items()):
            spend = b["spend"]
            impressions = b["impressions"]
            clicks = b["clicks"]
            purchases = b["purchases"]
            purchase_value = b["purchase_value"]
            reach = b["reach"]

            entry = {
                "date": d,
                "spend": round(spend, 4),
                "impressions": impressions,
                "reach": reach,
                "frequency": (b["frequency_sum"] / b["frequency_n"]) if b["frequency_n"] > 0 else 0.0,
                "clicks": clicks,
                "unique_clicks": b["unique_clicks"],
                "ctr": (clicks / impressions) if impressions > 0 else 0.0,
                "cpc": (spend / clicks) if clicks > 0 else 0.0,
                "cpm": (spend / impressions * 1000.0) if impressions > 0 else 0.0,
                "cpp": (spend / reach * 1000.0) if reach > 0 else 0.0,
                "purchases": purchases,
                "leads": b["leads"],
                "link_clicks": b["link_clicks"],
                "landing_page_views": b["landing_page_views"],
                "purchase_value": round(purchase_value, 4),
                "roas": (purchase_value / spend) if spend > 0 else 0.0,
                "cpa": (spend / purchases) if purchases > 0 else 0.0,
            }
            results.append(entry)

        return results
