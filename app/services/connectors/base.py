from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class ExternalField:
    """Represents a field available in the external data source."""
    name: str           # API/column name
    label: str          # Human-readable label
    field_type: str     # "string" | "number" | "date" | "boolean"


@dataclass
class SyncResult:
    """Result of a sync operation."""
    rows_fetched: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)


class BaseConnector(ABC):
    """Abstract base class for all data connectors."""

    def __init__(self, integration, db=None):
        self.integration = integration
        self.db = db

    @abstractmethod
    def test_connection(self) -> bool:
        """Test whether the connection is valid and credentials work."""
        ...

    @abstractmethod
    def get_available_fields(self) -> list[ExternalField]:
        """Fetch available fields/columns from the external source."""
        ...

    @abstractmethod
    def fetch_data(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """
        Fetch raw data from the external source.
        Returns list of dicts, each with a "date" key (date object) and field values:
        [{"date": date(2024, 1, 15), "Revenue": 50000, "Leads": 120}, ...]
        """
        ...

    @abstractmethod
    def refresh_auth(self) -> bool:
        """Refresh OAuth tokens or validate API keys. Returns True on success."""
        ...
