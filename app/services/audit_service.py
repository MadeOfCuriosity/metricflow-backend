from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import SuperAdmin, SuperAdminAuditLog


def log_action(
    db: Session,
    admin: SuperAdmin,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    commit: bool = True,
) -> SuperAdminAuditLog:
    """Record a super-administrator action in the audit log.

    Passes through the active SQLAlchemy session so it joins the same transaction
    as the action itself. Use ``commit=False`` when the caller will commit later.
    """
    entry = SuperAdminAuditLog(
        superadmin_id=admin.id,
        superadmin_email=admin.email,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details,
        ip_address=ip_address,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry
