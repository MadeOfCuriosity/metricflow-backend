"""App-specific admin routes for the WhatsApp Notifier app: the data-source
picker (existing KPIs/Data Fields to connect), recipient management
(manual + CSV), the opt-out suppression list, and a masked view of the
per-recipient send log. All writes go through AppContext's closure-based
accessors (never a raw query against these tables), the same tenancy
pattern BaseApp.run() itself is held to.
"""
import csv
import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin_org
from app.models import (
    User,
    Organization,
    KPIDefinition,
    DataField,
    WhatsAppRecipient,
    WhatsAppSuppression,
    WhatsAppSendLog,
)
from app.schemas.whatsapp_notifier import (
    DataSourceOption,
    DataSourceOptionsResponse,
    RecipientUpsertRequest,
    RecipientResponse,
    RecipientListResponse,
    RecipientsCsvImportResponse,
    SuppressionCreateRequest,
    SuppressionResponse,
    SuppressionListResponse,
    SendLogResponse,
    SendLogListResponse,
)
from app.services.app_installation_service import AppInstallationService
from app.services.apps.context import AppContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apps/whatsapp_notifier", tags=["Apps: WhatsApp Notifier"])

APP_KEY = "whatsapp_notifier"
CSV_REQUIRED_COLUMNS = {"name", "phone"}


def _mask_phone(phone: str) -> str:
    return f"***{phone[-4:]}" if phone and len(phone) >= 4 else "***"


def _get_installation_or_404(db: Session, org_id: uuid.UUID):
    installation = AppInstallationService.get_by_key(db, org_id, APP_KEY)
    if installation is None:
        raise HTTPException(status_code=404, detail=f"{APP_KEY} is not installed")
    return installation


def _context_for(db: Session, org_id: uuid.UUID, installation) -> AppContext:
    return AppContext(db=db, org_id=org_id, installation_id=installation.id, config=installation.config or {})


# --- Data source picker ---

@router.get("/data-sources", response_model=DataSourceOptionsResponse)
def list_data_sources(
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Existing KPIs and Data Fields this org already tracks, for the
    Connect Data Source picker at config time."""
    _, org = admin_org
    _get_installation_or_404(db, org.id)
    kpis = db.query(KPIDefinition).filter(KPIDefinition.org_id == org.id).all()
    data_fields = db.query(DataField).filter(DataField.org_id == org.id).all()
    return DataSourceOptionsResponse(
        kpis=[DataSourceOption(id=k.id, name=k.name) for k in kpis],
        data_fields=[DataSourceOption(id=f.id, name=f.name) for f in data_fields],
    )


# --- Recipients ---

@router.get("/recipients", response_model=RecipientListResponse)
def list_recipients(
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    _get_installation_or_404(db, org.id)
    rows = (
        db.query(WhatsAppRecipient)
        .filter(WhatsAppRecipient.org_id == org.id)
        .order_by(WhatsAppRecipient.name.asc())
        .all()
    )
    return RecipientListResponse(
        recipients=[RecipientResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.post("/recipients", response_model=RecipientResponse, status_code=201)
def upsert_recipient(
    data: RecipientUpsertRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Manual single-row add/update — matches an existing recipient by
    phone, otherwise inserts new."""
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id)
    context = _context_for(db, org.id, installation)
    row = context.upsert_recipient(name=data.name, phone=data.phone, notes=data.notes)
    return RecipientResponse.model_validate(row)


@router.delete("/recipients/{recipient_id}", status_code=204)
def remove_recipient(
    recipient_id: uuid.UUID,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id)
    context = _context_for(db, org.id, installation)
    if not context.remove_recipient(recipient_id):
        raise HTTPException(status_code=404, detail="Recipient not found")


@router.post("/recipients/import-csv", response_model=RecipientsCsvImportResponse)
def import_recipients_csv(
    file: UploadFile = File(...),
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    """Bulk intake: a CSV with columns name, phone, and optionally notes.
    Each row upserts independently — one bad row doesn't abort the rest."""
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id)
    context = _context_for(db, org.id, installation)

    raw = file.file.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))

    if reader.fieldnames is None or not CSV_REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must include columns: {', '.join(sorted(CSV_REQUIRED_COLUMNS))}",
        )

    imported = 0
    errors: list[str] = []
    for i, row in enumerate(reader, start=2):  # header is row 1
        try:
            name = (row.get("name") or "").strip()
            phone = (row.get("phone") or "").strip()
            if not name or not phone:
                raise ValueError("name and phone are required")
            context.upsert_recipient(name=name, phone=phone, notes=(row.get("notes") or "").strip() or None)
            imported += 1
        except Exception as e:
            errors.append(f"Row {i}: {e}")

    return RecipientsCsvImportResponse(imported=imported, errors=errors)


# --- Suppression list (opt-out) ---

@router.get("/suppressions", response_model=SuppressionListResponse)
def list_suppressions(
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    _get_installation_or_404(db, org.id)
    rows = db.query(WhatsAppSuppression).filter(WhatsAppSuppression.org_id == org.id).all()
    return SuppressionListResponse(suppressions=[SuppressionResponse.model_validate(r) for r in rows])


@router.post("/suppressions", response_model=SuppressionResponse, status_code=201)
def add_suppression(
    data: SuppressionCreateRequest,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id)
    context = _context_for(db, org.id, installation)
    row = context.add_suppression(data.phone, reason=data.reason or "manual")
    return SuppressionResponse.model_validate(row)


@router.delete("/suppressions/{phone}", status_code=204)
def remove_suppression(
    phone: str,
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    installation = _get_installation_or_404(db, org.id)
    context = _context_for(db, org.id, installation)
    if not context.remove_suppression(phone):
        raise HTTPException(status_code=404, detail="Number is not on the suppression list")


# --- Per-recipient send log (read-only, masked phone) ---

@router.get("/send-logs", response_model=SendLogListResponse)
def list_send_logs(
    limit: int = Query(50, ge=1, le=200),
    admin_org: tuple[User, Organization] = Depends(require_admin_org),
    db: Session = Depends(get_db),
):
    _, org = admin_org
    _get_installation_or_404(db, org.id)
    q = db.query(WhatsAppSendLog).filter(WhatsAppSendLog.org_id == org.id)
    total = q.count()
    rows = q.order_by(WhatsAppSendLog.created_at.desc()).limit(limit).all()
    return SendLogListResponse(
        logs=[
            SendLogResponse(
                id=r.id,
                run_id=r.run_id,
                recipient_name=r.recipient_name,
                phone_masked=_mask_phone(r.phone),
                data_value=r.data_value,
                template_used=r.template_used,
                whatsapp_message_id=r.whatsapp_message_id,
                delivery_status=r.delivery_status,
                error=r.error,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=total,
    )
