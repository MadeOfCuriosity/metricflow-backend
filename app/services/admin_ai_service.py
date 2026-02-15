"""
AI service for admin-only organizational data assistant using Google Gemini API.
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from app.core.config import settings
from app.models import (
    KPIDefinition,
    DataEntry,
    Insight,
    Room,
    User,
    RoomKPIAssignment,
)


ADMIN_AGENT_SYSTEM_PROMPT = """You are an AI assistant for a business metrics platform called MetricFlow. You help admins understand their organization's data, KPIs, and insights.

You have access to the organization's complete data context provided below. Use this data to answer questions accurately.

IMPORTANT RULES:
1. Always reference actual data from the context when answering questions.
2. If the user's question is unclear or could refer to multiple things, ASK CLARIFYING QUESTIONS before answering.
3. Be concise but thorough. Use numbers and specific KPI names when relevant.
4. If asked about data that doesn't exist in the context, clearly say so rather than making things up.
5. You can compare KPIs, identify trends, highlight concerns, and provide actionable recommendations.
6. Format responses for readability — use bullet points, bold text, and line breaks.
7. When asked about performance, reference the actual calculated values and trends.
8. If a KPI has no data entries, mention that data collection hasn't started for it.

{org_context}"""


@dataclass
class AdminAIResponse:
    """Response from the admin AI service."""
    text: str
    error: Optional[str] = None


@dataclass
class ConversationMessage:
    """A message in the conversation history."""
    role: str  # "user" or "assistant"
    content: str


class AdminAIService:
    """Service for admin AI assistant with full org data context."""

    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    @classmethod
    def _build_org_context(cls, db: Session, org_id: UUID) -> str:
        """
        Build a comprehensive data context string from org data.
        Includes KPIs, recent entries, insights, rooms, and users.
        """
        sections = []

        # 1. KPIs
        kpis = db.query(KPIDefinition).filter(
            KPIDefinition.org_id == org_id
        ).all()

        if kpis:
            kpi_lines = ["## Organization KPIs"]
            for kpi in kpis:
                kpi_lines.append(
                    f"- **{kpi.name}** (Category: {kpi.category}, "
                    f"Formula: {kpi.formula}, Period: {kpi.time_period}, "
                    f"Type: {'Preset' if kpi.is_preset else 'Custom'})"
                )
                if kpi.description:
                    kpi_lines.append(f"  Description: {kpi.description}")
            sections.append("\n".join(kpi_lines))
        else:
            sections.append("## Organization KPIs\nNo KPIs have been created yet.")

        # 2. Recent data entries (last 30 days)
        thirty_days_ago = date.today() - timedelta(days=30)
        entries = db.query(DataEntry).join(KPIDefinition).filter(
            KPIDefinition.org_id == org_id,
            DataEntry.date >= thirty_days_ago,
        ).order_by(DataEntry.date.desc()).limit(200).all()

        if entries:
            entry_lines = ["## Recent Data Entries (Last 30 Days)"]
            # Group by KPI
            kpi_entries: dict[str, list] = {}
            for entry in entries:
                kpi_name = entry.kpi_definition.name if entry.kpi_definition else "Unknown"
                if kpi_name not in kpi_entries:
                    kpi_entries[kpi_name] = []
                kpi_entries[kpi_name].append(entry)

            for kpi_name, kpi_data in kpi_entries.items():
                entry_lines.append(f"\n### {kpi_name}")
                for entry in kpi_data[:10]:  # Limit to 10 most recent per KPI
                    values_str = ", ".join(
                        f"{k}: {v}" for k, v in (entry.values or {}).items()
                    )
                    entry_lines.append(
                        f"  - Date: {entry.date}, "
                        f"Calculated Value: {entry.calculated_value}, "
                        f"Inputs: [{values_str}]"
                    )
                if len(kpi_data) > 10:
                    entry_lines.append(f"  - ... and {len(kpi_data) - 10} more entries")
            sections.append("\n".join(entry_lines))
        else:
            sections.append("## Recent Data Entries\nNo data entries in the last 30 days.")

        # 3. Active insights
        insights = db.query(Insight).filter(
            Insight.org_id == org_id
        ).order_by(Insight.priority.desc()).all()

        if insights:
            insight_lines = ["## Active Insights"]
            for insight in insights:
                kpi_name = ""
                if insight.kpi_id:
                    kpi = db.query(KPIDefinition).filter(
                        KPIDefinition.id == insight.kpi_id
                    ).first()
                    kpi_name = f" ({kpi.name})" if kpi else ""
                insight_lines.append(
                    f"- [{insight.priority.upper()}]{kpi_name} {insight.insight_text}"
                )
            sections.append("\n".join(insight_lines))
        else:
            sections.append("## Active Insights\nNo insights generated yet.")

        # 4. Rooms
        rooms = db.query(Room).filter(Room.org_id == org_id).all()
        if rooms:
            room_lines = ["## Rooms / Departments"]
            for room in rooms:
                parent_info = ""
                if room.parent_room_id:
                    parent = db.query(Room).filter(Room.id == room.parent_room_id).first()
                    parent_info = f" (under {parent.name})" if parent else ""

                # Count KPIs assigned to this room
                kpi_count = db.query(RoomKPIAssignment).filter(
                    RoomKPIAssignment.room_id == room.id
                ).count()
                room_lines.append(
                    f"- {room.name}{parent_info} — {kpi_count} KPIs assigned"
                )
            sections.append("\n".join(room_lines))

        # 5. Users
        users = db.query(User).filter(User.org_id == org_id).all()
        if users:
            user_lines = ["## Team Members"]
            for user in users:
                user_lines.append(
                    f"- {user.name} ({user.email}) — Role: {user.role_label or user.role}"
                )
            sections.append("\n".join(user_lines))

        # 6. Overall stats
        total_entries = db.query(DataEntry).join(KPIDefinition).filter(
            KPIDefinition.org_id == org_id
        ).count()

        days_of_data = db.query(func.count(distinct(DataEntry.date))).join(
            KPIDefinition
        ).filter(KPIDefinition.org_id == org_id).scalar() or 0

        stats_lines = ["## Overall Statistics"]
        stats_lines.append(f"- Total KPIs: {len(kpis)}")
        stats_lines.append(f"- Total Data Entries: {total_entries}")
        stats_lines.append(f"- Days of Data: {days_of_data}")
        stats_lines.append(f"- Active Insights: {len(insights) if insights else 0}")
        stats_lines.append(f"- Rooms: {len(rooms) if rooms else 0}")
        stats_lines.append(f"- Team Members: {len(users) if users else 0}")
        sections.append("\n".join(stats_lines))

        return "\n\n".join(sections)

    @classmethod
    async def generate_response(
        cls,
        db: Session,
        org_id: UUID,
        conversation_history: list[ConversationMessage],
        user_message: str,
    ) -> AdminAIResponse:
        """
        Generate an AI response with full org data context.
        """
        try:
            api_key = cls._get_api_key()
            url = f"{cls.GEMINI_API_URL}?key={api_key}"

            # Build org context
            org_context = cls._build_org_context(db, org_id)
            system_prompt = ADMIN_AGENT_SYSTEM_PROMPT.format(org_context=org_context)

            # Build conversation contents for Gemini API
            contents = []

            # System prompt as first exchange
            contents.append({
                "role": "user",
                "parts": [{"text": system_prompt}]
            })
            contents.append({
                "role": "model",
                "parts": [{"text": "I understand. I have access to your organization's complete data and I'm ready to help you analyze KPIs, insights, and metrics. What would you like to know?"}]
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
                    "maxOutputTokens": 2048,
                    "temperature": 0.7,
                    "topP": 0.9,
                }
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=30.0)
                response.raise_for_status()
                data = response.json()

            response_text = data["candidates"][0]["content"]["parts"][0]["text"]

            return AdminAIResponse(text=response_text)

        except ValueError as e:
            return AdminAIResponse(text="", error=str(e))
        except httpx.HTTPStatusError as e:
            return AdminAIResponse(
                text="",
                error=f"Gemini API error: {e.response.status_code}",
            )
        except Exception as e:
            return AdminAIResponse(
                text="",
                error=f"AI service error: {str(e)}",
            )

    @classmethod
    def generate_response_mock(
        cls,
        db: Session,
        org_id: UUID,
        conversation_history: list[ConversationMessage],
        user_message: str,
    ) -> AdminAIResponse:
        """Mock response for development without Gemini API key."""
        user_lower = user_message.lower()

        # Build context to provide somewhat relevant mock responses
        kpis = db.query(KPIDefinition).filter(
            KPIDefinition.org_id == org_id
        ).all()
        kpi_names = [kpi.name for kpi in kpis]

        insights = db.query(Insight).filter(
            Insight.org_id == org_id
        ).all()

        if "kpi" in user_lower or "metric" in user_lower or "performing" in user_lower:
            if kpi_names:
                kpi_list = "\n".join(f"- **{name}**" for name in kpi_names[:5])
                return AdminAIResponse(
                    text=f"Here are your organization's KPIs:\n\n{kpi_list}\n\nWould you like me to dive deeper into any specific KPI's performance?"
                )
            else:
                return AdminAIResponse(
                    text="Your organization hasn't set up any KPIs yet. Would you like to know how to get started?"
                )
        elif "insight" in user_lower or "alert" in user_lower or "attention" in user_lower:
            if insights:
                insight_list = "\n".join(
                    f"- [{i.priority.upper()}] {i.insight_text}" for i in insights[:5]
                )
                return AdminAIResponse(
                    text=f"Here are your current insights:\n\n{insight_list}\n\nWould you like me to explain any of these in more detail?"
                )
            else:
                return AdminAIResponse(
                    text="No active insights at the moment. This could mean your data is within normal ranges, or you may need to enter more data for the system to generate insights."
                )
        elif "help" in user_lower or "what can" in user_lower:
            return AdminAIResponse(
                text="I can help you with:\n\n- **KPI Performance** — Ask about any KPI's current value, trends, or comparisons\n- **Insights & Alerts** — View and understand automated insights\n- **Data Analysis** — Analyze patterns across your metrics\n- **Team & Rooms** — Information about your team structure\n\nWhat would you like to explore?"
            )
        else:
            # Ask for clarification
            if kpi_names:
                return AdminAIResponse(
                    text=f"Could you provide more context about what you'd like to know? For example, I can help you with:\n\n- Performance analysis for any of your {len(kpi_names)} KPIs\n- Recent trends and anomalies\n- Team activity and data entry status\n\nWhat specific area are you interested in?"
                )
            return AdminAIResponse(
                text="I'd be happy to help! Could you clarify what specific data or metrics you're interested in? I can analyze KPIs, insights, trends, and team activity."
            )

    @classmethod
    def _get_api_key(cls) -> str:
        """Get the Gemini API key from settings."""
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY environment variable not set")
        return settings.GEMINI_API_KEY
