#!/usr/bin/env python3
"""
Seed script to create demo organization with sample KPIs and 30 days of data.
Run with: python -m scripts.seed_demo_data
"""

import sys
import os
from datetime import datetime, timedelta
from uuid import uuid4
import random

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.organization import Organization
from app.models.user import User
from app.models.kpi_definition import KPIDefinition
from app.models.data_entry import DataEntry
from app.models.insight import Insight


def create_demo_data():
    """Create demo organization with sample data."""
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        # Check if demo org already exists
        existing_org = db.query(Organization).filter(
            Organization.slug == "demo-company"
        ).first()

        if existing_org:
            print("Demo organization already exists. Skipping seed.")
            return

        print("Creating demo organization...")

        # Create organization
        org = Organization(
            id=uuid4(),
            name="Demo Company",
            slug="demo-company",
        )
        db.add(org)
        db.flush()

        # Create demo user
        user = User(
            id=uuid4(),
            org_id=org.id,
            email="demo@metricflow.io",
            password_hash=get_password_hash("demo123"),
            full_name="Demo User",
            role="admin",
        )
        db.add(user)
        db.flush()

        print(f"Created user: demo@metricflow.io (password: demo123)")

        # Create KPIs
        kpis_data = [
            {
                "name": "Conversion Rate",
                "description": "Percentage of visitors who convert to customers",
                "category": "Sales",
                "formula": "(conversions / visitors) * 100",
                "input_fields": ["conversions", "visitors"],
                "unit": "%",
                "direction": "up",
            },
            {
                "name": "Customer Acquisition Cost",
                "description": "Average cost to acquire a new customer",
                "category": "Marketing",
                "formula": "marketing_spend / new_customers",
                "input_fields": ["marketing_spend", "new_customers"],
                "unit": "$",
                "direction": "down",
            },
            {
                "name": "Monthly Revenue",
                "description": "Total revenue for the month",
                "category": "Finance",
                "formula": "revenue",
                "input_fields": ["revenue"],
                "unit": "$",
                "direction": "up",
            },
            {
                "name": "Customer Satisfaction",
                "description": "Average customer satisfaction score",
                "category": "Operations",
                "formula": "satisfaction_score",
                "input_fields": ["satisfaction_score"],
                "unit": "pts",
                "direction": "up",
            },
            {
                "name": "Employee Productivity",
                "description": "Tasks completed per employee",
                "category": "Operations",
                "formula": "tasks_completed / employees",
                "input_fields": ["tasks_completed", "employees"],
                "unit": "",
                "direction": "up",
            },
            {
                "name": "Churn Rate",
                "description": "Percentage of customers who cancel",
                "category": "Sales",
                "formula": "(churned_customers / total_customers) * 100",
                "input_fields": ["churned_customers", "total_customers"],
                "unit": "%",
                "direction": "down",
            },
        ]

        kpis = []
        for kpi_data in kpis_data:
            kpi = KPIDefinition(
                id=uuid4(),
                org_id=org.id,
                name=kpi_data["name"],
                description=kpi_data["description"],
                category=kpi_data["category"],
                formula=kpi_data["formula"],
                input_fields=kpi_data["input_fields"],
                unit=kpi_data["unit"],
                direction=kpi_data["direction"],
                is_active=True,
            )
            db.add(kpi)
            kpis.append(kpi)

        db.flush()
        print(f"Created {len(kpis)} KPIs")

        # Generate 30 days of sample data
        today = datetime.now().date()
        entries_created = 0

        for days_ago in range(30, 0, -1):
            entry_date = today - timedelta(days=days_ago)

            for kpi in kpis:
                # Generate realistic-looking data based on KPI type
                if kpi.name == "Conversion Rate":
                    visitors = random.randint(800, 1500)
                    conversions = int(visitors * random.uniform(0.02, 0.05))
                    values = {"visitors": visitors, "conversions": conversions}
                    calculated = (conversions / visitors) * 100

                elif kpi.name == "Customer Acquisition Cost":
                    marketing_spend = random.randint(5000, 15000)
                    new_customers = random.randint(50, 150)
                    values = {"marketing_spend": marketing_spend, "new_customers": new_customers}
                    calculated = marketing_spend / new_customers

                elif kpi.name == "Monthly Revenue":
                    # Trend upward slightly
                    base_revenue = 50000 + (30 - days_ago) * 500
                    revenue = base_revenue + random.randint(-5000, 10000)
                    values = {"revenue": revenue}
                    calculated = revenue

                elif kpi.name == "Customer Satisfaction":
                    satisfaction_score = round(random.uniform(3.5, 4.8), 1)
                    values = {"satisfaction_score": satisfaction_score}
                    calculated = satisfaction_score

                elif kpi.name == "Employee Productivity":
                    employees = random.randint(45, 55)
                    tasks_completed = random.randint(200, 400)
                    values = {"tasks_completed": tasks_completed, "employees": employees}
                    calculated = tasks_completed / employees

                elif kpi.name == "Churn Rate":
                    total_customers = random.randint(900, 1100)
                    churned = random.randint(10, 30)
                    values = {"churned_customers": churned, "total_customers": total_customers}
                    calculated = (churned / total_customers) * 100

                else:
                    continue

                entry = DataEntry(
                    id=uuid4(),
                    kpi_id=kpi.id,
                    org_id=org.id,
                    date=entry_date,
                    values=values,
                    calculated_value=round(calculated, 2),
                    created_by=user.id,
                )
                db.add(entry)
                entries_created += 1

        db.flush()
        print(f"Created {entries_created} data entries (30 days)")

        # Create sample insights
        insights_data = [
            {
                "kpi_id": kpis[0].id,  # Conversion Rate
                "insight_type": "trend",
                "priority": "medium",
                "title": "Conversion rate showing positive trend",
                "description": "Your conversion rate has increased by 12% over the past 2 weeks. Consider analyzing which marketing channels are driving this improvement.",
            },
            {
                "kpi_id": kpis[1].id,  # CAC
                "insight_type": "anomaly",
                "priority": "high",
                "title": "Customer Acquisition Cost spike detected",
                "description": "CAC increased by 25% last week. Review recent marketing campaigns for efficiency opportunities.",
            },
            {
                "kpi_id": kpis[2].id,  # Revenue
                "insight_type": "milestone",
                "priority": "low",
                "title": "Revenue growth milestone",
                "description": "Monthly revenue has grown 15% compared to the previous month. Great progress!",
            },
        ]

        for insight_data in insights_data:
            insight = Insight(
                id=uuid4(),
                org_id=org.id,
                kpi_id=insight_data["kpi_id"],
                insight_type=insight_data["insight_type"],
                priority=insight_data["priority"],
                title=insight_data["title"],
                description=insight_data["description"],
                is_read=False,
            )
            db.add(insight)

        db.commit()
        print(f"Created {len(insights_data)} sample insights")
        print("\n" + "=" * 50)
        print("Demo data created successfully!")
        print("=" * 50)
        print(f"\nLogin credentials:")
        print(f"  Email: demo@metricflow.io")
        print(f"  Password: demo123")
        print(f"\nOrganization: Demo Company")
        print(f"KPIs: {len(kpis)}")
        print(f"Data entries: {entries_created}")
        print("=" * 50)

    except Exception as e:
        db.rollback()
        print(f"Error creating demo data: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_demo_data()
