"""
AI service for KPI building assistance using Google Gemini API.
"""
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.core.formula_parser import validate_formula


# System prompt for KPI building assistant
KPI_BUILDER_SYSTEM_PROMPT = """You are a KPI creation assistant for business metrics. Your job is to help users define custom KPIs.

When a user describes what they want to track:
1. Ask clarifying questions to understand their intent
2. Identify what data they can realistically collect
3. Suggest a formula using basic math operations (+, -, *, /, parentheses)
4. List the required input fields (use snake_case for field names)
5. IMPORTANT: Ask about the time period/frequency for data collection. Different metrics may have different collection frequencies (e.g., salary is monthly, tasks completed is daily)

Keep responses concise. After 2-3 exchanges, provide a concrete suggestion.

Important rules for formulas:
- Use only basic arithmetic: +, -, *, /, parentheses
- Variable names must be snake_case (e.g., total_revenue, deals_closed)
- No function calls or complex expressions
- Ensure the formula is mathematically valid

Time Period Guidelines:
- Ask users how often they will collect/enter data for this KPI
- daily: For metrics tracked every day (e.g., tasks completed, daily sales)
- weekly: For metrics tracked once a week (e.g., weekly reports)
- monthly: For metrics tracked once a month (e.g., salary, monthly revenue)
- quarterly: For metrics tracked quarterly (e.g., quarterly performance reviews)
- other: For irregular or custom intervals

When ready to suggest a KPI, format your response with:
[KPI_SUGGESTION]
name: <short descriptive name>
formula: <mathematical formula using snake_case variables>
input_fields: <comma-separated list of snake_case field names>
description: <one sentence description>
category: <Sales|Marketing|Operations|Finance|Custom>
time_period: <daily|weekly|monthly|quarterly|other>
[/KPI_SUGGESTION]

Examples of valid formulas:
- (revenue - costs) / revenue * 100
- total_leads / marketing_spend
- (new_customers - churned_customers) / total_customers * 100
"""


@dataclass
class KPISuggestion:
    """Structured KPI suggestion extracted from AI response."""
    name: str
    formula: str
    input_fields: list[str]
    description: Optional[str] = None
    category: str = "Custom"
    time_period: str = "daily"  # daily, weekly, monthly, quarterly, other


@dataclass
class AIResponse:
    """Response from the AI service."""
    text: str
    suggestion: Optional[KPISuggestion]
    error: Optional[str] = None


@dataclass
class ConversationMessage:
    """A message in the conversation history."""
    role: str  # "user" or "assistant"
    content: str


class AIRateLimiter:
    """Simple rate limiter for AI API calls."""

    @staticmethod
    def get_usage_count(db: Session, org_id: UUID, today: Optional[date] = None) -> int:
        """Get the number of AI calls made by an org today."""
        from app.models import Organization

        if today is None:
            today = date.today()

        # We'll store usage in a simple way using the Insight model's generated_at
        # For production, you'd want a dedicated AIUsage table
        # For now, we'll use a simple in-memory approach or cache

        # Check if we have a rate limit tracking mechanism
        # Using organization metadata or a dedicated table would be better
        # For simplicity, we'll allow the rate limit to be tracked externally
        return 0  # Placeholder - implement with Redis or DB table

    @staticmethod
    def check_rate_limit(db: Session, org_id: UUID) -> tuple[bool, int]:
        """
        Check if org is within rate limit.

        Returns:
            Tuple of (is_allowed, remaining_calls)
        """
        # For MVP, we'll implement a simple check
        # In production, use Redis or a dedicated table
        limit = settings.AI_RATE_LIMIT_PER_DAY
        current_usage = AIRateLimiter.get_usage_count(db, org_id)
        remaining = max(0, limit - current_usage)
        return current_usage < limit, remaining


class AIService:
    """Service for AI-powered KPI building assistance."""

    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    @classmethod
    def _get_api_key(cls) -> str:
        """Get the Gemini API key from settings."""
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY environment variable not set")
        return settings.GEMINI_API_KEY

    @staticmethod
    def parse_kpi_suggestion(text: str) -> Optional[KPISuggestion]:
        """
        Parse a KPI suggestion from AI response text.

        Looks for the [KPI_SUGGESTION] ... [/KPI_SUGGESTION] block.
        """
        pattern = r'\[KPI_SUGGESTION\](.*?)\[/KPI_SUGGESTION\]'
        match = re.search(pattern, text, re.DOTALL)

        if not match:
            return None

        suggestion_text = match.group(1).strip()

        # Parse the fields
        name = None
        formula = None
        input_fields = []
        description = None
        category = "Custom"
        time_period = "daily"  # Default to daily

        valid_time_periods = ['daily', 'weekly', 'monthly', 'quarterly', 'other']

        for line in suggestion_text.split('\n'):
            line = line.strip()
            if line.lower().startswith('name:'):
                name = line[5:].strip()
            elif line.lower().startswith('formula:'):
                formula = line[8:].strip()
            elif line.lower().startswith('input_fields:'):
                fields_str = line[13:].strip()
                input_fields = [f.strip() for f in fields_str.split(',') if f.strip()]
            elif line.lower().startswith('description:'):
                description = line[12:].strip()
            elif line.lower().startswith('category:'):
                cat = line[9:].strip()
                if cat in ['Sales', 'Marketing', 'Operations', 'Finance', 'Custom']:
                    category = cat
            elif line.lower().startswith('time_period:'):
                tp = line[12:].strip().lower()
                if tp in valid_time_periods:
                    time_period = tp

        # Validate we have required fields
        if not name or not formula or not input_fields:
            return None

        # Validate formula syntax
        is_valid, error, extracted_fields = validate_formula(formula)
        if not is_valid:
            return None

        return KPISuggestion(
            name=name,
            formula=formula,
            input_fields=input_fields,
            description=description,
            category=category,
            time_period=time_period,
        )

    @classmethod
    async def generate_response(
        cls,
        conversation_history: list[ConversationMessage],
        user_message: str,
    ) -> AIResponse:
        """
        Generate an AI response for the KPI builder conversation.

        Args:
            conversation_history: Previous messages in the conversation
            user_message: The current user message

        Returns:
            AIResponse with text and optional KPI suggestion
        """
        try:
            api_key = cls._get_api_key()
            url = f"{cls.GEMINI_API_URL}?key={api_key}"

            # Build conversation contents for Gemini API
            contents = []

            # Add system instruction as first user message
            contents.append({
                "role": "user",
                "parts": [{"text": KPI_BUILDER_SYSTEM_PROMPT}]
            })
            contents.append({
                "role": "model",
                "parts": [{"text": "I understand. I'll help users create KPIs following these guidelines."}]
            })

            # Add conversation history
            for msg in conversation_history:
                role = "user" if msg.role == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg.content}]
                })

            # Add current user message
            contents.append({
                "role": "user",
                "parts": [{"text": user_message}]
            })

            payload = {
                "contents": contents,
                "generationConfig": {
                    "maxOutputTokens": 1024,
                    "temperature": 0.7,
                    "topP": 0.9,
                }
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=30.0)
                response.raise_for_status()
                data = response.json()

            response_text = data["candidates"][0]["content"]["parts"][0]["text"]

            # Try to parse KPI suggestion from response
            suggestion = cls.parse_kpi_suggestion(response_text)

            # Clean up the response text for display (remove the suggestion block)
            display_text = re.sub(
                r'\[KPI_SUGGESTION\].*?\[/KPI_SUGGESTION\]',
                '',
                response_text,
                flags=re.DOTALL
            ).strip()

            # If there's a suggestion, add a clean summary
            if suggestion:
                display_text += f"\n\nI've prepared a KPI suggestion for you: **{suggestion.name}**"

            return AIResponse(
                text=display_text,
                suggestion=suggestion,
            )

        except ValueError as e:
            return AIResponse(
                text="",
                suggestion=None,
                error=str(e),
            )
        except httpx.HTTPStatusError as e:
            return AIResponse(
                text="",
                suggestion=None,
                error=f"Gemini API error: {e.response.status_code}",
            )
        except Exception as e:
            return AIResponse(
                text="",
                suggestion=None,
                error=f"AI service error: {str(e)}",
            )

    @classmethod
    def generate_response_mock(
        cls,
        conversation_history: list[ConversationMessage],
        user_message: str,
    ) -> AIResponse:
        """
        Mock response for testing without actual AI calls.
        """
        # Simple mock logic based on keywords
        user_lower = user_message.lower()

        if len(conversation_history) == 0:
            # First message
            if 'convert' in user_lower or 'rate' in user_lower:
                return AIResponse(
                    text="I'd be happy to help you create a conversion rate KPI! Could you tell me:\n1. What type of conversion are you measuring? (leads to customers, visitors to signups, etc.)\n2. Do you track both the starting count and the converted count?",
                    suggestion=None,
                )
            elif 'cost' in user_lower or 'spend' in user_lower:
                return AIResponse(
                    text="Let's create a cost-related KPI! To help you better:\n1. What costs are you tracking? (marketing, operations, etc.)\n2. What outcome do you want to measure against the cost?",
                    suggestion=None,
                )
            else:
                return AIResponse(
                    text="I can help you create a custom KPI! What business metric would you like to track? For example:\n- Conversion rates\n- Cost efficiency\n- Revenue metrics\n- Productivity measures",
                    suggestion=None,
                )
        else:
            # Follow-up - provide a suggestion
            if 'convert' in user_lower or 'lead' in user_lower or 'yes' in user_lower:
                return AIResponse(
                    text="Based on our conversation, here's a KPI suggestion:\n\n[KPI_SUGGESTION]\nname: Lead Conversion Rate\nformula: (converted_leads / total_leads) * 100\ninput_fields: converted_leads, total_leads\ndescription: Percentage of leads that convert to customers\ncategory: Sales\ntime_period: daily\n[/KPI_SUGGESTION]\n\nI've prepared a KPI suggestion for you: **Lead Conversion Rate**",
                    suggestion=KPISuggestion(
                        name="Lead Conversion Rate",
                        formula="(converted_leads / total_leads) * 100",
                        input_fields=["converted_leads", "total_leads"],
                        description="Percentage of leads that convert to customers",
                        category="Sales",
                        time_period="daily",
                    ),
                )
            else:
                return AIResponse(
                    text="Could you provide more details about what you want to measure? What data points do you have available to track? Also, how often will you be collecting this data (daily, weekly, monthly)?",
                    suggestion=None,
                )
