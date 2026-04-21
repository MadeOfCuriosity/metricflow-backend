from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PlanResponse(BaseModel):
    code: str
    razorpay_plan_id: str


class PlanListResponse(BaseModel):
    plans: list[PlanResponse]


class CreateSubscriptionRequest(BaseModel):
    plan_code: str = Field(..., min_length=1, max_length=50)
    total_count: int = Field(12, ge=1, le=120)  # number of billing cycles


class CreateSubscriptionResponse(BaseModel):
    subscription_id: str
    razorpay_key_id: str
    plan_code: str
    short_url: Optional[str] = None


class VerifySubscriptionRequest(BaseModel):
    razorpay_subscription_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class SubscriptionResponse(BaseModel):
    id: UUID
    plan_code: str
    razorpay_subscription_id: str
    status: str
    total_count: Optional[int]
    paid_count: int
    current_start: Optional[datetime]
    current_end: Optional[datetime]
    ended_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
