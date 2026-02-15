from typing import Optional

from pydantic import BaseModel, Field


class ConversationMessageInput(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class KPISuggestionResponse(BaseModel):
    name: str
    formula: str
    input_fields: list[str]
    description: Optional[str] = None
    category: str = "Custom"
    time_period: str = "daily"


class KPIBuilderRequest(BaseModel):
    conversation_history: list[ConversationMessageInput] = Field(default_factory=list)
    user_message: str = Field(..., min_length=1, max_length=1000)


class KPIBuilderResponse(BaseModel):
    ai_response: str
    suggested_kpi: Optional[KPISuggestionResponse] = None
    error: Optional[str] = None
    rate_limit_remaining: Optional[int] = None


class RateLimitStatusResponse(BaseModel):
    allowed: bool
    remaining_calls: int
    limit_per_day: int
    resets_at: str  # ISO timestamp


class AdminAgentRequest(BaseModel):
    conversation_history: list[ConversationMessageInput] = Field(default_factory=list)
    user_message: str = Field(..., min_length=1, max_length=2000)


class AdminAgentResponse(BaseModel):
    ai_response: str
    error: Optional[str] = None
    rate_limit_remaining: Optional[int] = None
