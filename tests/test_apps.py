"""Tests for the Apps/Extensions framework: lifecycle, tenant isolation, idempotency."""

import uuid

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.models import KPIDefinition, OrgAppInstallation, AppRunRecord
from app.services.app_installation_service import AppInstallationService, AppInstallationError
from app.services.app_runner import AppRunner
from app.services.apps.context import AppContext

REFERENCE_APP_KEY = "reference_health"


def _register_org(client, org_name, email):
    resp = client.post("/api/auth/register-org", json={
        "org_name": org_name,
        "admin_email": email,
        "admin_password": "TestPassword123",
        "admin_name": "Test Admin",
    })
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    body = resp.json()
    return {
        "Authorization": f"Bearer {body['access_token']}",
    }, body["organization"]["id"]


class TestAppLifecycle:
    @pytest.fixture
    def org_a(self, client):
        return _register_org(client, "Org A", "admin-a@test.com")

    def test_list_excludes_dev_only_reference_app(self, client, org_a):
        """reference_health is dev_only — it must stay installable/runnable
        by key (the rest of this suite exercises that) but never show up in
        the org-facing app listing real users see."""
        headers, _ = org_a
        resp = client.get("/api/apps", headers=headers)
        assert resp.status_code == 200
        apps = resp.json()["apps"]
        assert all(a["key"] != REFERENCE_APP_KEY for a in apps)

    def test_install_then_duplicate_install_fails(self, client, org_a):
        headers, _ = org_a
        resp = client.post(f"/api/apps/{REFERENCE_APP_KEY}/install", headers=headers)
        assert resp.status_code == 201
        installation = resp.json()
        assert installation["is_enabled"] is False
        assert installation["entitlement_status"] == "not_required"

        resp2 = client.post(f"/api/apps/{REFERENCE_APP_KEY}/install", headers=headers)
        assert resp2.status_code == 400

    def test_configure_then_enable_then_disable(self, client, org_a):
        headers, _ = org_a
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/install", headers=headers)

        resp = client.put(
            f"/api/apps/{REFERENCE_APP_KEY}/config",
            json={"config": {"greeting": "Hi there"}},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["config"]["greeting"] == "Hi there"

        resp = client.post(f"/api/apps/{REFERENCE_APP_KEY}/enable", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is True

        resp = client.post(f"/api/apps/{REFERENCE_APP_KEY}/disable", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False

    def test_run_requires_enabled(self, client, org_a):
        headers, _ = org_a
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/install", headers=headers)
        resp = client.post(f"/api/apps/{REFERENCE_APP_KEY}/run", json={}, headers=headers)
        assert resp.status_code == 400

    def test_run_produces_run_record(self, client, org_a):
        headers, _ = org_a
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/install", headers=headers)
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/enable", headers=headers)

        resp = client.post(f"/api/apps/{REFERENCE_APP_KEY}/run", json={}, headers=headers)
        assert resp.status_code == 200
        run = resp.json()
        assert run["status"] == "success"
        assert run["trigger_type"] == "on_demand"
        assert run["result"]["kpi_count"] == 0
        assert run["started_at"] is not None
        assert run["completed_at"] is not None

        logs = client.get(f"/api/apps/{REFERENCE_APP_KEY}/runs", headers=headers)
        assert logs.status_code == 200
        assert logs.json()["total"] == 1

    def test_run_is_idempotent_on_same_key(self, client, org_a):
        headers, _ = org_a
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/install", headers=headers)
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/enable", headers=headers)

        key = f"retry-{uuid.uuid4()}"
        first = client.post(
            f"/api/apps/{REFERENCE_APP_KEY}/run", json={"idempotency_key": key}, headers=headers
        )
        second = client.post(
            f"/api/apps/{REFERENCE_APP_KEY}/run", json={"idempotency_key": key}, headers=headers
        )
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        logs = client.get(f"/api/apps/{REFERENCE_APP_KEY}/runs", headers=headers)
        assert logs.json()["total"] == 1, "retried run must not create a second run-record"

    def test_uninstall_removes_state_and_blocks_future_actions(self, client, org_a, db_session):
        headers, org_id = org_a
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/install", headers=headers)
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/enable", headers=headers)
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/run", json={}, headers=headers)

        installation = db_session.query(OrgAppInstallation).filter(
            OrgAppInstallation.org_id == uuid.UUID(org_id),
            OrgAppInstallation.app_key == REFERENCE_APP_KEY,
        ).first()
        installation_id = installation.id

        from app.core.scheduler import scheduler
        assert scheduler.get_job(f"app_{installation_id}") is not None

        resp = client.delete(f"/api/apps/{REFERENCE_APP_KEY}", headers=headers)
        assert resp.status_code == 204

        # No orphaned scheduler job survives uninstall.
        assert scheduler.get_job(f"app_{installation_id}") is None

        # All installation state (and cascaded run records) is gone.
        assert db_session.query(OrgAppInstallation).filter(
            OrgAppInstallation.id == installation_id
        ).first() is None
        assert db_session.query(AppRunRecord).filter(
            AppRunRecord.installation_id == installation_id
        ).count() == 0

        # Nothing fires and no run can be created against the deleted installation.
        resp = client.post(f"/api/apps/{REFERENCE_APP_KEY}/run", json={}, headers=headers)
        assert resp.status_code == 404

        # Reinstalling is possible (unique org_id+app_key constraint isn't violated by history).
        resp = client.post(f"/api/apps/{REFERENCE_APP_KEY}/install", headers=headers)
        assert resp.status_code == 201


class TestCrossTenantIsolation:
    """The central security guarantee: an app run under org A's context must
    never see org B's data, and no app code path can obtain a raw Session."""

    def test_app_context_never_exposes_a_session(self, db_session):
        context = AppContext(
            db=db_session, org_id=uuid.uuid4(), installation_id=uuid.uuid4(), config={},
        )
        for value in vars(context).values():
            assert not isinstance(value, Session), (
                "AppContext must never expose the raw DB Session as an attribute"
            )

    def test_run_under_org_a_never_returns_org_b_data(self, client, db_session):
        headers_a, org_a_id = _register_org(client, "Org A", "iso-a@test.com")
        headers_b, org_b_id = _register_org(client, "Org B", "iso-b@test.com")

        # Seed KPIs only in org B.
        for name in ("Org B KPI 1", "Org B KPI 2"):
            resp = client.post(
                "/api/kpis",
                json={
                    "name": name,
                    "description": "org b data",
                    "category": "Sales",
                    "formula": "revenue",
                },
                headers=headers_b,
            )
            assert resp.status_code == 201, resp.text

        assert db_session.query(KPIDefinition).filter(
            KPIDefinition.org_id == uuid.UUID(org_b_id)
        ).count() == 2

        # Install + enable + run the reference app under org A, which has zero KPIs.
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/install", headers=headers_a)
        client.post(f"/api/apps/{REFERENCE_APP_KEY}/enable", headers=headers_a)
        run = client.post(f"/api/apps/{REFERENCE_APP_KEY}/run", json={}, headers=headers_a)
        assert run.status_code == 200
        assert run.json()["result"]["kpi_count"] == 0, (
            "org A's run must not see org B's KPIs"
        )

        # Now add a KPI to org A and confirm the count reflects only org A's own data.
        resp = client.post(
            "/api/kpis",
            json={
                "name": "Org A KPI",
                "description": "org a data",
                "category": "Sales",
                "formula": "revenue",
            },
            headers=headers_a,
        )
        assert resp.status_code == 201

        run2 = client.post(
            f"/api/apps/{REFERENCE_APP_KEY}/run",
            json={"idempotency_key": f"after-seed-{uuid.uuid4()}"},
            headers=headers_a,
        )
        assert run2.json()["result"]["kpi_count"] == 1

        # Sanity: org B's installation state is completely independent (org A never installed for B).
        # reference_health is dev_only and excluded from /api/apps, so check via /run instead
        # of the listing: an org with no installation gets a 404, not a 200.
        run_b = client.post(f"/api/apps/{REFERENCE_APP_KEY}/run", json={}, headers=headers_b)
        assert run_b.status_code == 404


class TestEntitlementGate:
    """No app in the registry requires an entitlement today, so this drives
    AppInstallationService directly against a synthetic 'requires_entitlement' row."""

    def test_enable_blocked_until_granted(self, db_session, client):
        headers, org_id = _register_org(client, "Org Ent", "ent@test.com")
        installation = AppInstallationService.install(
            db_session, uuid.UUID(org_id), REFERENCE_APP_KEY, None
        )
        # Simulate an entitlement-gated app without needing a second registry entry.
        installation.entitlement_status = "required"
        db_session.commit()

        with pytest.raises(AppInstallationError):
            AppInstallationService.set_enabled(db_session, installation, True)

        AppInstallationService.set_entitlement(db_session, installation, "granted")
        installation = AppInstallationService.set_enabled(db_session, installation, True)
        assert installation.is_enabled is True

        # Revoking entitlement disables the app immediately.
        AppInstallationService.set_entitlement(db_session, installation, "revoked")
        assert installation.is_enabled is False


class TestStaleRunCleanup:
    def test_stale_running_record_is_marked_failed(self, db_session):
        from datetime import datetime, timedelta

        headers = None
        org_id = uuid.uuid4()
        installation = OrgAppInstallation(
            org_id=org_id, app_key=REFERENCE_APP_KEY, is_enabled=True, config={},
        )
        db_session.add(installation)
        db_session.commit()

        stale = AppRunRecord(
            installation_id=installation.id,
            org_id=org_id,
            app_key=REFERENCE_APP_KEY,
            status="running",
            trigger_type="scheduled",
            idempotency_key="stale-1",
            started_at=datetime.utcnow() - timedelta(minutes=60),
        )
        db_session.add(stale)
        db_session.commit()

        cleaned = AppRunner.cleanup_stale_runs(db_session, timeout_minutes=30)
        assert cleaned == 1
        db_session.refresh(stale)
        assert stale.status == "failed"
        assert stale.completed_at is not None
