import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app.core.config import settings
from app.core.encryption import encrypt_value, decrypt_value
from app.services.connectors.base import BaseConnector, ExternalField

logger = logging.getLogger(__name__)

ZOHO_AUTH_URI = f"https://accounts.zoho.{settings.ZOHO_DC}/oauth/v2/auth"
ZOHO_TOKEN_URI = f"https://accounts.zoho.{settings.ZOHO_DC}/oauth/v2/token"
ZOHO_BOOKS_API_BASE = f"https://www.zohoapis.{settings.ZOHO_DC}/books/v3"
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

# "gl_revenue" is not a document module — it attributes invoice line items to a
# specific Chart of Accounts GL (e.g. "SMM Sales", "PM Sales"). Zoho's invoice
# LIST endpoint doesn't expose per-line-item account_id, so this mode fetches
# each invoice's full detail to read line_items and filters/sums by GL account.
# Safety cap on invoice detail calls per sync — orgs with heavy invoice volume
# would otherwise trigger hundreds of extra API calls in one run.
GL_REVENUE_MODULE = "gl_revenue"
MAX_GL_REVENUE_INVOICES_PER_SYNC = 1000

# "gl_expense" is the same idea as gl_revenue but for costs (e.g. per-department
# salary GLs) which post via Journal Entries, not invoices — Zoho payroll/manual
# journals debit a department's expense account and credit a payable/bank
# account, so this sums the debit side of line items matching gl_account_id.
GL_EXPENSE_MODULE = "gl_expense"
MAX_GL_EXPENSE_JOURNALS_PER_SYNC = 1000


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

        if module == GL_REVENUE_MODULE:
            # Fields come from invoice line_items, not the invoice list — fixed
            # set, since discovering them would require a full detail fetch.
            return [
                ExternalField(name="item_total", label="Line Item Total", field_type="number"),
                ExternalField(name="quantity", label="Quantity", field_type="number"),
            ]

        if module == GL_EXPENSE_MODULE:
            return [
                ExternalField(name="amount", label="Debit Amount", field_type="number"),
            ]

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

    def _get_detail_with_retry(
        self,
        client: httpx.Client,
        endpoint: str,
        record_id: str,
        org_id: str,
        response_key: str,
        max_attempts: int = 4,
    ) -> Optional[dict]:
        """
        Fetch one record's detail (invoice or journal), retrying on
        rate-limit/transient errors.

        Returns the record dict, or None only for a confirmed 404 (record
        genuinely gone — safe to skip). Any other non-200 (429 rate limit,
        5xx, network error) is retried with backoff; if still failing after
        max_attempts, raises so the sync fails loudly instead of silently
        under-counting revenue/expense as if the missing records contributed
        zero.
        """
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = client.get(
                    f"{ZOHO_BOOKS_API_BASE}/{endpoint}/{record_id}",
                    headers=self._get_headers(),
                    params={"organization_id": org_id},
                )
            except httpx.HTTPError as e:
                last_error = str(e)
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 200:
                return resp.json().get(response_key, {})
            if resp.status_code == 404:
                return None

            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if attempt < max_attempts:
                time.sleep(2 ** attempt)

        raise RuntimeError(
            f"Failed to fetch Zoho Books {response_key} {record_id} after {max_attempts} "
            f"attempts (likely rate-limited): {last_error}"
        )

    def _fetch_gl_revenue(
        self,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> list[dict]:
        """
        Attribute invoice line items to the configured GL account (Chart of
        Accounts entry, e.g. "SMM Sales"), aggregated by day.

        Zoho's invoice list endpoint only gives invoice-level totals, not
        which GL account each line item posted to — that's only on the full
        invoice detail. So this lists invoices in range, then fetches each
        one's detail to sum the line items matching gl_account_id.
        """
        config = self.integration.config or {}
        org_id = self._get_org_id()
        gl_account_id = config.get("gl_account_id")
        if not gl_account_id:
            logger.error("Zoho Books gl_revenue sync missing required 'gl_account_id' config")
            return []

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        # Step 1: list invoice IDs + dates in range (cheap, paginated). Any
        # failure here raises (via raise_for_status / the retry loop's own
        # errors) rather than silently returning [] — a listing failure must
        # not be mistaken for "no invoices in range."
        invoice_stubs: list[tuple[str, date]] = []
        page = 1
        with httpx.Client(timeout=30) as client:
            while True:
                resp = client.get(
                    f"{ZOHO_BOOKS_API_BASE}/invoices",
                    headers=self._get_headers(),
                    params={
                        "organization_id": org_id,
                        "date_start": start_date.strftime(ZOHO_DATE_FORMAT),
                        "date_end": end_date.strftime(ZOHO_DATE_FORMAT),
                        "page": page,
                        "per_page": 200,
                        "sort_column": "date",
                        "sort_order": "A",
                    },
                )
                if resp.status_code == 204:
                    break
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    raise RuntimeError(f"Zoho Books API error listing invoices: {data.get('message')}")

                for inv in data.get("invoices", []):
                    raw_date = inv.get("date", "")
                    try:
                        inv_date = datetime.strptime(raw_date[:10], ZOHO_DATE_FORMAT).date()
                    except (ValueError, TypeError):
                        continue
                    invoice_stubs.append((inv["invoice_id"], inv_date))

                page_context = data.get("page_context", {})
                if not page_context.get("has_more_page", False):
                    break
                page += 1
                if page > 50:
                    break

        if len(invoice_stubs) > MAX_GL_REVENUE_INVOICES_PER_SYNC:
            logger.warning(
                f"Zoho Books gl_revenue sync: {len(invoice_stubs)} invoices in range, "
                f"capping detail fetch at {MAX_GL_REVENUE_INVOICES_PER_SYNC} (narrow the "
                f"date range or sync more often to cover the rest)."
            )
            invoice_stubs = invoice_stubs[:MAX_GL_REVENUE_INVOICES_PER_SYNC]

        # Step 2: fetch each invoice's detail, sum line items matching the GL account
        date_totals: dict[date, dict[str, float]] = defaultdict(
            lambda: {"item_total": 0.0, "quantity": 0.0, "count": 0}
        )
        with httpx.Client(timeout=30) as client:
            for i, (invoice_id, inv_date) in enumerate(invoice_stubs):
                if i > 0:
                    time.sleep(0.3)  # spread calls out — proactively avoid rate limits
                detail = self._get_detail_with_retry(client, "invoices", invoice_id, org_id, "invoice")
                if detail is None:
                    # Only a confirmed 404 (invoice genuinely gone) reaches here —
                    # anything else (rate limit, 5xx, network error) raises instead
                    # of silently under-counting revenue as if it were zero.
                    continue

                for line in detail.get("line_items", []):
                    if line.get("account_id") != gl_account_id:
                        continue
                    bucket = date_totals[inv_date]
                    bucket["item_total"] += float(line.get("item_total") or 0)
                    bucket["quantity"] += float(line.get("quantity") or 0)
                    bucket["count"] += 1

        rows = []
        for record_date, totals in sorted(date_totals.items()):
            rows.append({
                "date": record_date,
                "item_total__sum": totals["item_total"],
                "item_total__count": totals["count"],
                "item_total__avg": totals["item_total"] / totals["count"] if totals["count"] else 0,
                "quantity__sum": totals["quantity"],
                "__record_count": totals["count"],
            })
        return rows

    def _fetch_gl_expense(
        self,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> list[dict]:
        """
        Attribute Journal Entry line items to the configured GL account (e.g.
        a per-department Salary GL), aggregated by day.

        Mirrors _fetch_gl_revenue but sources from /journals instead of
        /invoices — payroll and manual journals debit an expense account and
        credit a payable/bank account, so only the debit side is summed
        (the credit side is the offsetting entry, not the cost itself).
        """
        config = self.integration.config or {}
        org_id = self._get_org_id()
        gl_account_id = config.get("gl_account_id")
        if not gl_account_id:
            logger.error("Zoho Books gl_expense sync missing required 'gl_account_id' config")
            return []

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        # Step 1: list journal IDs + dates in range (cheap, paginated)
        journal_stubs: list[tuple[str, date]] = []
        page = 1
        with httpx.Client(timeout=30) as client:
            while True:
                resp = client.get(
                    f"{ZOHO_BOOKS_API_BASE}/journals",
                    headers=self._get_headers(),
                    params={
                        "organization_id": org_id,
                        "date_start": start_date.strftime(ZOHO_DATE_FORMAT),
                        "date_end": end_date.strftime(ZOHO_DATE_FORMAT),
                        "page": page,
                        "per_page": 200,
                        "sort_column": "journal_date",
                        "sort_order": "A",
                    },
                )
                if resp.status_code == 204:
                    break
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    raise RuntimeError(f"Zoho Books API error listing journals: {data.get('message')}")

                for j in data.get("journals", []):
                    raw_date = j.get("journal_date", "")
                    try:
                        j_date = datetime.strptime(raw_date[:10], ZOHO_DATE_FORMAT).date()
                    except (ValueError, TypeError):
                        continue
                    journal_stubs.append((j["journal_id"], j_date))

                page_context = data.get("page_context", {})
                if not page_context.get("has_more_page", False):
                    break
                page += 1
                if page > 50:
                    break

        if len(journal_stubs) > MAX_GL_EXPENSE_JOURNALS_PER_SYNC:
            logger.warning(
                f"Zoho Books gl_expense sync: {len(journal_stubs)} journals in range, "
                f"capping detail fetch at {MAX_GL_EXPENSE_JOURNALS_PER_SYNC} (narrow the "
                f"date range or sync more often to cover the rest)."
            )
            journal_stubs = journal_stubs[:MAX_GL_EXPENSE_JOURNALS_PER_SYNC]

        # Step 2: fetch each journal's detail, sum debit-side line items matching the GL account
        date_totals: dict[date, dict[str, float]] = defaultdict(lambda: {"amount": 0.0, "count": 0})
        with httpx.Client(timeout=30) as client:
            for i, (journal_id, j_date) in enumerate(journal_stubs):
                if i > 0:
                    time.sleep(0.3)  # spread calls out — proactively avoid rate limits
                detail = self._get_detail_with_retry(client, "journals", journal_id, org_id, "journal")
                if detail is None:
                    continue

                for line in detail.get("line_items", []):
                    if line.get("account_id") != gl_account_id:
                        continue
                    if line.get("debit_or_credit") != "debit":
                        continue
                    bucket = date_totals[j_date]
                    bucket["amount"] += float(line.get("amount") or 0)
                    bucket["count"] += 1

        rows = []
        for record_date, totals in sorted(date_totals.items()):
            rows.append({
                "date": record_date,
                "amount__sum": totals["amount"],
                "amount__count": totals["count"],
                "amount__avg": totals["amount"] / totals["count"] if totals["count"] else 0,
                "__record_count": totals["count"],
            })
        return rows

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

        if module == GL_REVENUE_MODULE:
            return self._fetch_gl_revenue(start_date, end_date)

        if module == GL_EXPENSE_MODULE:
            return self._fetch_gl_expense(start_date, end_date)

        module_info = BOOKS_MODULES.get(module, BOOKS_MODULES["invoices"])
        org_id = self._get_org_id()
        date_field = config.get("date_field", module_info["date_field"])
        branch_id = config.get("branch_id")

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
                    if branch_id:
                        params["branch_id"] = branch_id

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
