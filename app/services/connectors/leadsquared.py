import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from app.core.encryption import decrypt_value
from app.services.connectors.base import BaseConnector, ExternalField

logger = logging.getLogger(__name__)

LEADSQUARED_DATE_FORMAT = "%Y-%m-%d"


class LeadSquaredConnector(BaseConnector):
    """Connector for LeadSquared API (API Key + Secret auth)."""

    def _get_base_url(self) -> str:
        """Get the LeadSquared API base URL from config."""
        config = self.integration.config or {}
        # LeadSquared has region-specific URLs
        region = config.get("region", "")
        if region:
            return f"https://{region}.leadsquared.com/v2"
        return "https://api.leadsquared.com/v2"

    def _get_auth_params(self) -> dict:
        """Get authentication query parameters."""
        api_key = decrypt_value(self.integration.api_key_encrypted) if self.integration.api_key_encrypted else ""
        api_secret = decrypt_value(self.integration.api_secret_encrypted) if self.integration.api_secret_encrypted else ""
        return {
            "accessKey": api_key,
            "secretKey": api_secret,
        }

    def test_connection(self) -> bool:
        """Test connection by fetching lead metadata."""
        try:
            base_url = self._get_base_url()
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    f"{base_url}/LeadManagement.svc/LeadsMetaData.Get",
                    params=self._get_auth_params(),
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"LeadSquared connection test failed: {e}")
            return False

    def refresh_auth(self) -> bool:
        """LeadSquared uses API keys — no refresh needed. Just validate."""
        return self.test_connection()

    def get_available_fields(self) -> list[ExternalField]:
        """Fetch available lead fields from LeadSquared metadata."""
        config = self.integration.config or {}
        data_type = config.get("data_type", "leads")

        try:
            base_url = self._get_base_url()
            with httpx.Client(timeout=15) as client:
                if data_type == "activities":
                    resp = client.get(
                        f"{base_url}/ActivityType.svc/Retrieve",
                        params=self._get_auth_params(),
                    )
                    resp.raise_for_status()
                    activities = resp.json()

                    fields = []
                    for act in activities if isinstance(activities, list) else []:
                        fields.append(ExternalField(
                            name=act.get("ActivityEventId", str(act.get("Id", ""))),
                            label=act.get("ActivityEvent", "Unknown"),
                            field_type="number",  # Activities are typically counted
                        ))
                    return fields
                else:
                    # Leads metadata
                    resp = client.get(
                        f"{base_url}/LeadManagement.svc/LeadsMetaData.Get",
                        params=self._get_auth_params(),
                    )
                    resp.raise_for_status()
                    metadata = resp.json()

                    fields = []
                    for field_meta in metadata if isinstance(metadata, list) else []:
                        field_type = "string"
                        schema_name = field_meta.get("SchemaName", "")
                        data_type_val = field_meta.get("DataType", "").lower()

                        if data_type_val in ("number", "currency", "double", "int"):
                            field_type = "number"
                        elif data_type_val in ("date", "datetime"):
                            field_type = "date"
                        elif data_type_val == "boolean":
                            field_type = "boolean"

                        fields.append(ExternalField(
                            name=schema_name,
                            label=field_meta.get("DisplayName", schema_name),
                            field_type=field_type,
                        ))
                    return fields
        except Exception as e:
            logger.error(f"Failed to fetch LeadSquared fields: {e}")
            return []

    def fetch_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Fetch leads/activities from LeadSquared, aggregate by date.
        Returns list of dicts with "date" key and aggregated values.
        """
        config = self.integration.config or {}
        data_type = config.get("data_type", "leads")
        date_field = config.get("date_field", "CreatedOn")

        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        base_url = self._get_base_url()
        all_records = []

        try:
            with httpx.Client(timeout=30) as client:
                if data_type == "activities":
                    # Fetch activities
                    body = {
                        "Parameter": {
                            "FromDate": start_date.strftime("%Y-%m-%d 00:00:00"),
                            "ToDate": end_date.strftime("%Y-%m-%d 23:59:59"),
                        },
                        "Paging": {
                            "PageIndex": 1,
                            "PageSize": 1000,
                        },
                    }
                    resp = client.post(
                        f"{base_url}/ProspectActivity.svc/Retrieve",
                        params=self._get_auth_params(),
                        json=body,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict):
                            all_records = data.get("ProspectActivities", data.get("List", []))
                        elif isinstance(data, list):
                            all_records = data
                else:
                    # Fetch leads with date filter
                    body = {
                        "Parameter": {
                            "LookupName": date_field,
                            "LookupValue": start_date.strftime(LEADSQUARED_DATE_FORMAT),
                            "Operator": "GreaterThanOrEqualTo",
                        },
                        "Columns": {
                            "Include_CSV": f"{date_field},FirstName,LastName,EmailAddress,mx_Revenue,mx_Deal_Value,Source",
                        },
                        "Sorting": {
                            "ColumnName": date_field,
                            "Direction": "1",
                        },
                        "Paging": {
                            "PageIndex": 1,
                            "PageSize": 1000,
                        },
                    }
                    resp = client.post(
                        f"{base_url}/LeadManagement.svc/Leads.Get",
                        params=self._get_auth_params(),
                        json=body,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict):
                            all_records = data.get("Leads", data.get("List", []))
                        elif isinstance(data, list):
                            all_records = data
        except Exception as e:
            logger.error(f"Failed to fetch LeadSquared data: {e}")
            return []

        # Group records by date
        date_groups: dict[date, list[dict]] = defaultdict(list)
        for record in all_records:
            raw_date = record.get(date_field, "")
            if not raw_date:
                continue

            record_date = None
            if isinstance(raw_date, str):
                # Try common formats
                for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"]:
                    try:
                        record_date = datetime.strptime(raw_date[:19], fmt).date()
                        break
                    except ValueError:
                        continue

            if record_date is None:
                continue
            if record_date < start_date or record_date > end_date:
                continue

            date_groups[record_date].append(record)

        # Aggregate by date
        rows = []
        for record_date, records in sorted(date_groups.items()):
            entry = {"date": record_date, "__record_count": len(records)}

            # Pre-compute aggregations for numeric fields
            numeric_sums: dict[str, float] = defaultdict(float)
            numeric_counts: dict[str, int] = defaultdict(int)

            for rec in records:
                for key, val in rec.items():
                    if key == date_field:
                        continue
                    parsed = None
                    if isinstance(val, (int, float)):
                        parsed = float(val)
                    elif isinstance(val, str):
                        try:
                            parsed = float(val.replace(",", ""))
                        except ValueError:
                            pass
                    if parsed is not None:
                        numeric_sums[key] += parsed
                        numeric_counts[key] += 1

            for field_name in numeric_sums:
                entry[f"{field_name}__sum"] = numeric_sums[field_name]
                entry[f"{field_name}__count"] = numeric_counts[field_name]
                entry[f"{field_name}__avg"] = (
                    numeric_sums[field_name] / numeric_counts[field_name]
                    if numeric_counts[field_name] > 0
                    else 0
                )

            rows.append(entry)

        return rows
