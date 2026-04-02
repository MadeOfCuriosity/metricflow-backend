#!/usr/bin/env python3
"""
Dynamic demo data generator — reads persona JSON configs and seeds the database.

Each persona file defines an org's rooms, data fields, KPIs, data generation
parameters, and AI insights. No data is hardcoded here — everything is driven
by the persona config.

Usage:
    # Seed all personas in the personas/ directory:
    python -m scripts.seed_personas

    # Seed a specific persona:
    python -m scripts.seed_personas --persona agency_suspended_creatives

    # Re-seed (delete existing demo org and recreate):
    python -m scripts.seed_personas --reset

    # Custom date range:
    python -m scripts.seed_personas --days 90
"""

import sys
import os
import json
import math
import random
import argparse
from datetime import datetime, timedelta, date
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.organization import Organization
from app.models.user import User
from app.models.room import Room
from app.models.kpi_definition import KPIDefinition
from app.models.data_field import DataField
from app.models.data_field_room import DataFieldRoom
from app.models.data_field_entry import DataFieldEntry
from app.models.data_entry import DataEntry
from app.models.kpi_data_field import KPIDataField
from app.models.room_kpi_assignment import RoomKPIAssignment
from app.models.insight import Insight


PERSONAS_DIR = Path(__file__).parent / "personas"


# ---------------------------------------------------------------------------
#  Data Generation Engine
# ---------------------------------------------------------------------------

def generate_value(gen_config: dict, day_index: int, day_of_week: int) -> float:
    """
    Generate a single realistic value for a data field on a given day.

    Parameters from gen_config:
        baseline     — starting value
        trend        — change per day (positive = growth, negative = decline)
        variance     — standard deviation of random noise
        min / max    — hard clamps
        weekend_factor — multiplier for Sat/Sun (0 = skip, 0.1 = very low, 1 = normal)
        integer      — if true, round to int
        anomaly_chance — probability of a 2-3x spike/dip (default 0.03)
        seasonality_amplitude — optional monthly wave amplitude
    """
    baseline = gen_config["baseline"]
    trend = gen_config.get("trend", 0)
    variance = gen_config.get("variance", 0)
    val_min = gen_config.get("min", 0)
    val_max = gen_config.get("max", float("inf"))
    weekend_factor = gen_config.get("weekend_factor", 1)
    anomaly_chance = gen_config.get("anomaly_chance", 0.03)
    seasonality_amp = gen_config.get("seasonality_amplitude", 0)
    is_integer = gen_config.get("integer", False)

    # Base value with trend
    value = baseline + (trend * day_index)

    # Monthly seasonality (optional)
    if seasonality_amp:
        value += seasonality_amp * math.sin(2 * math.pi * day_index / 30)

    # Random noise
    if variance:
        value += random.gauss(0, variance)

    # Weekend adjustment
    if day_of_week >= 5:  # Saturday=5, Sunday=6
        if weekend_factor == 0:
            return 0  # No activity on weekends
        value *= weekend_factor

    # Anomaly injection
    if random.random() < anomaly_chance:
        # Sometimes spike, sometimes dip
        if random.random() < 0.5:
            value *= random.uniform(1.8, 2.5)
        else:
            value *= random.uniform(0.3, 0.6)

    # Clamp
    value = max(val_min, min(val_max, value))

    if is_integer:
        value = max(int(round(value)), int(val_min))
    else:
        value = round(value, 2)

    return value


def evaluate_formula(formula: str, values: dict) -> float:
    """Safely evaluate a KPI formula with given variable values."""
    try:
        # Only allow basic math operations on the provided variables
        allowed = {k: v for k, v in values.items() if isinstance(v, (int, float))}
        result = eval(formula, {"__builtins__": {}}, allowed)
        if isinstance(result, (int, float)) and not math.isnan(result) and not math.isinf(result):
            return round(result, 2)
    except (ZeroDivisionError, TypeError, NameError):
        pass
    return 0.0


# ---------------------------------------------------------------------------
#  Room Tree Builder
# ---------------------------------------------------------------------------

def create_rooms(db, org_id, user_id, room_configs, parent_id=None):
    """Recursively create rooms and return a name->id mapping."""
    room_map = {}
    for rc in room_configs:
        room = Room(
            id=uuid4(),
            org_id=org_id,
            name=rc["name"],
            description=rc.get("description", ""),
            parent_room_id=parent_id,
            created_by=user_id,
        )
        db.add(room)
        db.flush()
        room_map[rc["name"]] = room.id

        # Recurse into children
        children = rc.get("children", [])
        if children:
            child_map = create_rooms(db, org_id, user_id, children, parent_id=room.id)
            room_map.update(child_map)

    return room_map


# ---------------------------------------------------------------------------
#  Main Seeder
# ---------------------------------------------------------------------------

def seed_persona(db, persona_path: str, days_override: int = None):
    """Seed a single persona from a JSON config file."""

    with open(persona_path, "r") as f:
        config = json.load(f)

    org_config = config["org"]
    data_days = days_override or config.get("data_days", 120)

    # Check if org already exists
    existing = db.query(Organization).filter(
        Organization.name == org_config["name"]
    ).first()

    if existing:
        print(f"  [SKIP] Organization '{org_config['name']}' already exists. Use --reset to recreate.")
        return False

    print(f"\n{'='*60}")
    print(f"  Seeding: {org_config['name']}")
    print(f"  Industry: {org_config.get('industry', 'N/A')}")
    print(f"  Story: {config.get('story', 'N/A')[:80]}...")
    print(f"  Data: {data_days} days")
    print(f"{'='*60}")

    # --- 1. Create Organization ---
    org = Organization(
        id=uuid4(),
        name=org_config["name"],
        industry=org_config.get("industry"),
    )
    db.add(org)
    db.flush()
    print(f"  [+] Organization: {org.name}")

    # --- 2. Create User ---
    user = User(
        id=uuid4(),
        org_id=org.id,
        email=org_config["email"],
        password_hash=get_password_hash(org_config["password"]),
        name=org_config.get("user_name", "Demo User"),
        auth_provider="email",
        role="admin",
        role_label=org_config.get("role_label", "Admin"),
    )
    db.add(user)
    db.flush()
    print(f"  [+] User: {user.email} (password: {org_config['password']})")

    # --- 3. Create Rooms ---
    room_map = create_rooms(db, org.id, user.id, config.get("rooms", []))
    print(f"  [+] Rooms: {len(room_map)} created")
    for name in room_map:
        print(f"      - {name}")

    # --- 4. Create Data Fields & assign to rooms ---
    field_map = {}  # variable_name -> DataField.id
    for fc in config.get("data_fields", []):
        field = DataField(
            id=uuid4(),
            org_id=org.id,
            name=fc["name"],
            variable_name=fc["variable_name"],
            description=fc.get("description", ""),
            unit=fc.get("unit", ""),
            entry_interval=fc.get("entry_interval", "daily"),
            created_by=user.id,
        )
        db.add(field)
        db.flush()
        field_map[fc["variable_name"]] = field.id

        # Assign field to room
        room_name = fc.get("room")
        if room_name and room_name in room_map:
            dfr = DataFieldRoom(
                id=uuid4(),
                data_field_id=field.id,
                room_id=room_map[room_name],
            )
            db.add(dfr)

    db.flush()
    print(f"  [+] Data Fields: {len(field_map)} created")

    # --- 5. Create KPIs, link to fields & rooms ---
    kpi_map = {}  # kpi_name -> KPIDefinition.id
    for kc in config.get("kpis", []):
        kpi = KPIDefinition(
            id=uuid4(),
            org_id=org.id,
            name=kc["name"],
            description=kc.get("description", ""),
            formula=kc["formula"],
            input_fields=kc["input_fields"],
            category=kc.get("category", "Custom"),
            time_period="daily",
            is_preset=False,
            is_shared=False,
            created_by=user.id,
        )
        db.add(kpi)
        db.flush()
        kpi_map[kc["name"]] = kpi.id

        # Link KPI to data fields
        for var_name in kc["input_fields"]:
            if var_name in field_map:
                kdf = KPIDataField(
                    id=uuid4(),
                    kpi_id=kpi.id,
                    data_field_id=field_map[var_name],
                    variable_name=var_name,
                )
                db.add(kdf)

        # Assign KPI to room
        room_name = kc.get("room")
        if room_name and room_name in room_map:
            rka = RoomKPIAssignment(
                id=uuid4(),
                room_id=room_map[room_name],
                kpi_id=kpi.id,
                assigned_by=user.id,
                aggregation_method=kc.get("aggregation_method", "sum"),
            )
            db.add(rka)

    db.flush()
    print(f"  [+] KPIs: {len(kpi_map)} created")

    # --- 6. Generate daily data ---
    generators = config.get("field_generators", {})
    today = date.today()
    start_date = today - timedelta(days=data_days)

    field_entries_count = 0
    data_entries_count = 0

    # Pre-build KPI lookup: kpi_name -> (kpi_id, formula, input_fields, room_name)
    kpi_lookup = {}
    for kc in config.get("kpis", []):
        kpi_id = kpi_map.get(kc["name"])
        if kpi_id:
            kpi_lookup[kc["name"]] = {
                "id": kpi_id,
                "formula": kc["formula"],
                "input_fields": kc["input_fields"],
                "room": kc.get("room"),
            }

    print(f"  [~] Generating {data_days} days of data...")

    for day_offset in range(data_days):
        current_date = start_date + timedelta(days=day_offset)
        dow = current_date.weekday()  # 0=Mon, 6=Sun

        # Generate all field values for this day
        daily_values = {}
        for var_name, gen_config in generators.items():
            if var_name.startswith("_"):
                continue  # skip comments

            value = generate_value(gen_config, day_offset, dow)

            # Skip zero-value weekend entries for fields with weekend_factor=0
            if value == 0 and gen_config.get("weekend_factor", 1) == 0 and dow >= 5:
                continue

            daily_values[var_name] = value

            # Create DataFieldEntry
            if var_name in field_map:
                dfe = DataFieldEntry(
                    id=uuid4(),
                    org_id=org.id,
                    data_field_id=field_map[var_name],
                    date=current_date,
                    value=value,
                    entered_by=user.id,
                )
                db.add(dfe)
                field_entries_count += 1

        # Calculate and create KPI DataEntries
        for kpi_name, kpi_info in kpi_lookup.items():
            # Gather input values for this KPI
            kpi_values = {}
            has_all = True
            for var in kpi_info["input_fields"]:
                if var in daily_values:
                    kpi_values[var] = daily_values[var]
                else:
                    has_all = False
                    break

            if not has_all:
                continue

            calculated = evaluate_formula(kpi_info["formula"], kpi_values)

            room_id = None
            room_name = kpi_info.get("room")
            if room_name and room_name in room_map:
                room_id = room_map[room_name]

            entry = DataEntry(
                id=uuid4(),
                org_id=org.id,
                kpi_id=kpi_info["id"],
                room_id=room_id,
                date=current_date,
                values=kpi_values,
                calculated_value=calculated,
                entered_by=user.id,
            )
            db.add(entry)
            data_entries_count += 1

        # Flush every 10 days to avoid huge memory usage
        if day_offset % 10 == 0:
            db.flush()

    db.flush()
    print(f"  [+] Data Field Entries: {field_entries_count:,}")
    print(f"  [+] KPI Data Entries: {data_entries_count:,}")

    # --- 7. Create Insights ---
    insights_count = 0
    for ic in config.get("insights", []):
        kpi_id = kpi_map.get(ic.get("kpi_name"))
        insight = Insight(
            id=uuid4(),
            org_id=org.id,
            kpi_id=kpi_id,
            insight_text=ic["text"],
            priority=ic.get("priority", "medium"),
        )
        db.add(insight)
        insights_count += 1

    db.flush()
    print(f"  [+] Insights: {insights_count}")

    print(f"\n  {'='*56}")
    print(f"  DONE: {org_config['name']}")
    print(f"  Login: {org_config['email']} / {org_config['password']}")
    print(f"  {'='*56}\n")

    return True


def delete_persona_org(db, org_name: str):
    """Delete an organization and all cascaded data."""
    org = db.query(Organization).filter(Organization.name == org_name).first()
    if org:
        db.delete(org)
        db.flush()
        print(f"  [x] Deleted organization: {org_name}")
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Seed demo data from persona configs")
    parser.add_argument(
        "--persona",
        type=str,
        help="Seed a specific persona file (without .json extension)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing demo orgs before re-seeding",
    )
    parser.add_argument(
        "--days",
        type=int,
        help="Override the number of days of data to generate",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available persona configs",
    )
    args = parser.parse_args()

    # List available personas
    if args.list:
        print("\nAvailable personas:")
        for p in sorted(PERSONAS_DIR.glob("*.json")):
            with open(p) as f:
                config = json.load(f)
            print(f"  - {p.stem}: {config['org']['name']} ({config['org'].get('industry', 'N/A')})")
        return

    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        # Determine which persona files to process
        if args.persona:
            persona_file = PERSONAS_DIR / f"{args.persona}.json"
            if not persona_file.exists():
                print(f"Error: Persona file not found: {persona_file}")
                print(f"Available: {[p.stem for p in PERSONAS_DIR.glob('*.json')]}")
                sys.exit(1)
            persona_files = [persona_file]
        else:
            persona_files = sorted(PERSONAS_DIR.glob("*.json"))

        if not persona_files:
            print("No persona files found in", PERSONAS_DIR)
            sys.exit(1)

        print(f"\nFound {len(persona_files)} persona(s) to seed:")
        for p in persona_files:
            print(f"  - {p.stem}")

        seeded = 0
        for persona_file in persona_files:
            with open(persona_file) as f:
                config = json.load(f)

            org_name = config["org"]["name"]

            if args.reset:
                delete_persona_org(db, org_name)

            if seed_persona(db, str(persona_file), days_override=args.days):
                seeded += 1

        db.commit()
        print(f"\n{'='*60}")
        print(f"  All done! Seeded {seeded} organization(s).")
        print(f"{'='*60}")

    except Exception as e:
        db.rollback()
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
