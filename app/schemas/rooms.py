from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RoomCreateRequest(BaseModel):
    """Request to create a new room."""
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    parent_room_id: Optional[UUID] = None


class RoomUpdateRequest(BaseModel):
    """Request to update an existing room."""
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None


class RoomResponse(BaseModel):
    """Response containing room details."""
    id: UUID
    org_id: UUID
    name: str
    description: Optional[str]
    parent_room_id: Optional[UUID]
    created_by: Optional[UUID]
    created_at: datetime
    kpi_count: int = 0
    sub_room_count: int = 0

    model_config = {"from_attributes": True}


class RoomTreeNode(BaseModel):
    """Nested tree structure for room hierarchy."""
    id: UUID
    name: str
    description: Optional[str]
    children: list["RoomTreeNode"] = []
    kpi_count: int = 0


class RoomListResponse(BaseModel):
    """Response containing list of rooms."""
    rooms: list[RoomResponse]
    total: int


class RoomTreeResponse(BaseModel):
    """Response containing room tree structure."""
    rooms: list[RoomTreeNode]


class AssignKPIsRequest(BaseModel):
    """Request to assign KPIs to a room."""
    kpi_ids: list[UUID] = Field(..., min_length=1)


class AssignKPIsResponse(BaseModel):
    """Response after assigning KPIs to a room."""
    message: str
    assigned_count: int


class RoomKPIResponse(BaseModel):
    """Response for KPIs in a room context."""
    room_kpis: list  # KPIResponse objects
    shared_kpis: list  # KPIResponse objects (org-wide)
    room: RoomResponse


class RoomBreadcrumb(BaseModel):
    """Breadcrumb item for room hierarchy navigation."""
    id: UUID
    name: str


class AggregatedKPIEntry(BaseModel):
    """Single date point of aggregated KPI data from sub-rooms."""
    date: date
    aggregated_value: float
    sub_room_count: int


class SubRoomBreakdown(BaseModel):
    """Per-sub-room value for a KPI."""
    room_id: str
    room_name: str
    value: float


class AggregatedKPIResponse(BaseModel):
    """KPI with aggregated data computed from sub-rooms."""
    kpi: dict  # KPIResponse-compatible dict
    aggregation_method: str = "sum"
    current_aggregated_value: Optional[float] = None
    previous_aggregated_value: Optional[float] = None
    recent_entries: list[AggregatedKPIEntry] = []
    breakdown: list[SubRoomBreakdown] = []


class RoomDashboardResponse(BaseModel):
    """Response containing room dashboard data."""
    room: RoomResponse
    breadcrumbs: list[RoomBreadcrumb]
    room_kpis: list  # KPIResponse objects
    sub_room_kpis: list = []  # KPIResponse objects (rolled up from sub-rooms)
    aggregated_kpis: list[AggregatedKPIResponse] = []  # Aggregated from sub-rooms
    shared_kpis: list  # KPIResponse objects


# Allow forward reference resolution
RoomTreeNode.model_rebuild()
