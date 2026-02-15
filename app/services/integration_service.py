import uuid
import secrets
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.encryption import encrypt_value
from app.models.integration import Integration
from app.models.integration_field_mapping import IntegrationFieldMapping
from app.models.sync_log import SyncLog
from app.models.data_field import DataField
from app.schemas.integrations import (
    CreateIntegrationRequest,
    UpdateIntegrationRequest,
    FieldMappingInput,
    IntegrationResponse,
    FieldMappingResponse,
)

logger = logging.getLogger(__name__)


class IntegrationService:
    """CRUD operations for integrations and field mappings."""

    @staticmethod
    def get_all(db: Session, org_id: UUID) -> list[Integration]:
        """Get all integrations for an organization."""
        return db.query(Integration).filter(
            Integration.org_id == org_id,
        ).order_by(Integration.created_at.desc()).all()

    @staticmethod
    def get_by_id(db: Session, integration_id: UUID, org_id: UUID) -> Integration | None:
        """Get a single integration by ID, scoped to org."""
        return db.query(Integration).filter(
            Integration.id == integration_id,
            Integration.org_id == org_id,
        ).first()

    @staticmethod
    def create(
        db: Session,
        org_id: UUID,
        user_id: UUID,
        data: CreateIntegrationRequest,
    ) -> Integration:
        """Create a new integration."""
        status = "pending_auth"

        # For LeadSquared (API key auth), try to connect immediately
        if data.provider == "leadsquared" and data.api_key and data.api_secret:
            status = "connected"

        integration = Integration(
            org_id=org_id,
            created_by=user_id,
            provider=data.provider,
            display_name=data.display_name,
            status=status,
            config=data.config,
            sync_schedule=data.sync_schedule,
        )

        # Encrypt and store API keys for LeadSquared
        if data.provider == "leadsquared" and data.api_key and data.api_secret:
            integration.api_key_encrypted = encrypt_value(data.api_key)
            integration.api_secret_encrypted = encrypt_value(data.api_secret)

        db.add(integration)
        db.commit()
        db.refresh(integration)
        return integration

    @staticmethod
    def update(
        db: Session,
        integration: Integration,
        data: UpdateIntegrationRequest,
    ) -> Integration:
        """Update an integration's config or schedule."""
        if data.display_name is not None:
            integration.display_name = data.display_name
        if data.sync_schedule is not None:
            integration.sync_schedule = data.sync_schedule
        if data.config is not None:
            integration.config = data.config

        integration.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(integration)
        return integration

    @staticmethod
    def delete(db: Session, integration: Integration) -> None:
        """Delete an integration and all related data."""
        db.delete(integration)
        db.commit()

    @staticmethod
    def update_oauth_tokens(
        db: Session,
        integration: Integration,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
    ) -> Integration:
        """Store encrypted OAuth tokens after successful authorization."""
        integration.access_token_encrypted = encrypt_value(access_token)
        if refresh_token:
            integration.refresh_token_encrypted = encrypt_value(refresh_token)
        if expires_at:
            integration.token_expires_at = expires_at
        integration.status = "connected"
        integration.error_message = None
        integration.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(integration)
        return integration

    @staticmethod
    def set_error(db: Session, integration: Integration, error_message: str) -> None:
        """Set integration status to error with a message."""
        integration.status = "error"
        integration.error_message = error_message
        integration.updated_at = datetime.utcnow()
        db.commit()

    # --- Field Mappings ---

    @staticmethod
    def get_mappings(db: Session, integration_id: UUID) -> list[IntegrationFieldMapping]:
        """Get all field mappings for an integration."""
        return db.query(IntegrationFieldMapping).filter(
            IntegrationFieldMapping.integration_id == integration_id,
        ).all()

    @staticmethod
    def set_mappings(
        db: Session,
        integration_id: UUID,
        mappings: list[FieldMappingInput],
    ) -> list[IntegrationFieldMapping]:
        """Replace all field mappings for an integration."""
        # Delete existing mappings
        db.query(IntegrationFieldMapping).filter(
            IntegrationFieldMapping.integration_id == integration_id,
        ).delete()

        created = []
        for m in mappings:
            mapping = IntegrationFieldMapping(
                integration_id=integration_id,
                data_field_id=m.data_field_id,
                external_field_name=m.external_field_name,
                external_field_label=m.external_field_label,
                aggregation=m.aggregation,
                filter_criteria=m.filter_criteria,
            )
            db.add(mapping)
            created.append(mapping)

        db.commit()
        for m in created:
            db.refresh(m)
        return created

    # --- Sync Logs ---

    @staticmethod
    def get_sync_logs(
        db: Session,
        integration_id: UUID,
        limit: int = 20,
    ) -> list[SyncLog]:
        """Get recent sync logs for an integration."""
        return db.query(SyncLog).filter(
            SyncLog.integration_id == integration_id,
        ).order_by(SyncLog.started_at.desc()).limit(limit).all()

    # --- OAuth State ---

    @staticmethod
    def generate_oauth_state(integration_id: UUID) -> str:
        """Generate a CSRF-safe OAuth state parameter."""
        csrf_token = secrets.token_urlsafe(32)
        return f"{integration_id}:{csrf_token}"

    @staticmethod
    def parse_oauth_state(state: str) -> tuple[UUID | None, str]:
        """Parse OAuth state into integration_id and csrf_token."""
        try:
            parts = state.split(":", 1)
            if len(parts) != 2:
                return None, ""
            return UUID(parts[0]), parts[1]
        except (ValueError, IndexError):
            return None, ""

    # --- Helpers ---

    @staticmethod
    def to_response(integration: Integration) -> IntegrationResponse:
        """Convert an Integration model to response schema."""
        return IntegrationResponse(
            id=integration.id,
            org_id=integration.org_id,
            provider=integration.provider,
            display_name=integration.display_name,
            status=integration.status,
            error_message=integration.error_message,
            config=integration.config or {},
            sync_schedule=integration.sync_schedule,
            last_synced_at=integration.last_synced_at,
            next_sync_at=integration.next_sync_at,
            created_at=integration.created_at,
            updated_at=integration.updated_at,
            mapping_count=len(integration.field_mappings) if integration.field_mappings else 0,
        )

    @staticmethod
    def mapping_to_response(mapping: IntegrationFieldMapping) -> FieldMappingResponse:
        """Convert a mapping model to response schema."""
        data_field_name = ""
        if mapping.data_field:
            data_field_name = mapping.data_field.name
        return FieldMappingResponse(
            id=mapping.id,
            integration_id=mapping.integration_id,
            data_field_id=mapping.data_field_id,
            data_field_name=data_field_name,
            external_field_name=mapping.external_field_name,
            external_field_label=mapping.external_field_label,
            aggregation=mapping.aggregation,
            is_active=mapping.is_active,
        )
