from datetime import datetime
from pydantic import BaseModel


class CompletionRateEntry(BaseModel):
    date: str
    rate: float


class AdminStatsResponse(BaseModel):
    total_users: int
    total_kpis: int
    total_rooms: int
    active_integrations: int
    total_data_entries: int
    today_data_entries: int
    completion_rate: list[CompletionRateEntry]


class ActivityEntry(BaseModel):
    id: str
    type: str
    description: str
    user_name: str | None = None
    timestamp: datetime
    metadata: dict = {}


class ActivityFeedResponse(BaseModel):
    activities: list[ActivityEntry]
    total: int
