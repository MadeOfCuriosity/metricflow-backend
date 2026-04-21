#!/usr/bin/env python3
"""Create or activate a super-administrator allow-list entry.

Run with:
    python -m scripts.create_superadmin --email you@example.com --name "Your Name"

Only emails in the ``superadmins`` table can log into the /superadmin panel via
Google. This script bootstraps the first entry (additional admins can then be
invited from within the panel).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.superadmin import SuperAdmin


def main():
    parser = argparse.ArgumentParser(description="Create a super-administrator entry.")
    parser.add_argument("--email", required=True, help="Google account email")
    parser.add_argument("--name", default=None, help="Display name (optional)")
    args = parser.parse_args()

    email = args.email.lower().strip()
    if "@" not in email:
        print(f"Invalid email: {email}")
        sys.exit(1)

    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        existing = (
            db.query(SuperAdmin).filter(func.lower(SuperAdmin.email) == email).first()
        )
        if existing:
            if not existing.is_active:
                existing.is_active = True
                db.commit()
                print(f"Reactivated existing super-administrator: {email}")
            else:
                print(f"Super-administrator already exists and is active: {email}")
            return

        admin = SuperAdmin(
            email=email,
            name=args.name,
            is_active=True,
            created_by_email="cli-bootstrap",
        )
        db.add(admin)
        db.commit()
        print(f"Created super-administrator: {email}")
        print("Log in at /superadmin/login using Google sign-in with this email.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
