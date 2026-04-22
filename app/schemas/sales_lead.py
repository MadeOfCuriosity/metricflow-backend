from datetime import datetime
from typing import Optional, List, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


SalesLeadStatus = Literal["new", "contacted", "qualified", "won", "lost"]


class SalesLeadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    company: Optional[str] = Field(default=None, max_length=255)
    team_size: Optional[str] = Field(default=None, max_length=50)
    message: Optional[str] = Field(default=None, max_length=2000)
    source: Optional[str] = Field(default="enterprise_contact", max_length=50)


class SalesLeadUpdate(BaseModel):
    status: Optional[SalesLeadStatus] = None
    notes: Optional[str] = Field(default=None, max_length=5000)


class SalesLeadResponse(BaseModel):
    id: UUID
    name: str
    email: str
    company: Optional[str] = None
    team_size: Optional[str] = None
    message: Optional[str] = None
    source: str
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SalesLeadListResponse(BaseModel):
    items: List[SalesLeadResponse]
    total: int
