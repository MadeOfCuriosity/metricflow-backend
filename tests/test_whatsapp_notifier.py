"""Tests for the WhatsApp Notifier app: connecting a KPI/Data Field as the
data source, tenant isolation, per-recipient idempotency, and suppression.
All outbound WhatsApp calls are monkeypatched — these tests never touch the
real Graph API.
"""
import uuid
from datetime import date

import pytest
from fastapi import status

from app.models import WhatsAppSendLog, WhatsAppRecipient
from app.services.app_installation_service import AppInstallationService
import app.services.apps.whatsapp_notifier as notifier_module

APP_KEY = "whatsapp_notifier"
TODAY = date.today().isoformat()


def _register_org(client, org_name, email):
    resp = client.post("/api/auth/register-org", json={
        "org_name": org_name,
        "admin_email": email,
        "admin_password": "TestPassword123",
        "admin_name": "Test Admin",
    })
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    body = resp.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["organization"]["id"]


def _create_data_field_with_value(client, headers, name, value):
    resp = client.post("/api/data-fields", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    field_id = resp.json()["id"]

    resp = client.post(
        "/api/entries/fields",
        json={"date": TODAY, "entries": [{"data_field_id": field_id, "value": value}]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return field_id


def _create_kpi_with_value(client, headers, name, value):
    resp = client.post(
        "/api/kpis",
        json={"name": name, "description": "test kpi", "category": "Sales", "formula": "revenue"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    kpi_id = resp.json()["id"]

    resp = client.post(
        "/api/entries",
        json={"date": TODAY, "entries": [{"kpi_id": kpi_id, "values": {"revenue": value}}]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return kpi_id


def _grant_entitlement(db_session, org_id):
    """The app declares requires_entitlement=True; v1 entitlement is
    manual/superadmin-set only (no billing plumbing)."""
    installation = AppInstallationService.get_by_key(db_session, uuid.UUID(org_id), APP_KEY)
    AppInstallationService.set_entitlement(db_session, installation, "granted")


def _install_and_configure(
    client, headers, org_id, db_session, *, data_source_kind, data_source_id,
    threshold_comparison="none", threshold_value=None,
):
    resp = client.post(f"/api/apps/{APP_KEY}/install", headers=headers)
    assert resp.status_code == 201, resp.text

    config = {
        "template_name": "kpi_update",
        "data_source_kind": data_source_kind,
        "data_source_id": data_source_id,
        "threshold_comparison": threshold_comparison,
    }
    if threshold_value is not None:
        config["threshold_value"] = threshold_value

    resp = client.put(f"/api/apps/{APP_KEY}/config", json={"config": config}, headers=headers)
    assert resp.status_code == 200, resp.text

    resp = client.put(
        f"/api/apps/{APP_KEY}/secret-config",
        json={"secret_config": {
            "waba_phone_number_id": "1234567890",
            "waba_access_token": "test-access-token-abcd",
        }},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "test-access-token-abcd" not in resp.text  # never echoed back

    _grant_entitlement(db_session, org_id)
    resp = client.post(f"/api/apps/{APP_KEY}/enable", headers=headers)
    assert resp.status_code == 200, resp.text


def _add_recipient(client, headers, *, name="Priya Sharma", phone="+919990001111", notes=None):
    resp = client.post(
        f"/api/apps/{APP_KEY}/recipients",
        json={"name": name, "phone": phone, "notes": notes},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture(autouse=True)
def fake_whatsapp(monkeypatch):
    """Never hit the real Graph API — return a fake message id for every send."""
    sent_calls = []

    def fake_send_template(**kwargs):
        sent_calls.append(kwargs)
        return "wamid.FAKE123"

    monkeypatch.setattr(notifier_module, "send_template_message", fake_send_template)
    return sent_calls


class TestDataSourceConnection:
    def test_data_source_options_lists_existing_kpis_and_fields(self, client, db_session):
        headers, org_id = _register_org(client, "Picker Org", "picker@test.com")
        client.post(f"/api/apps/{APP_KEY}/install", headers=headers)

        field_id = _create_data_field_with_value(client, headers, "Outstanding Receivables", 42000)
        kpi_id = _create_kpi_with_value(client, headers, "Daily Revenue", 10000)

        resp = client.get(f"/api/apps/{APP_KEY}/data-sources", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert any(f["id"] == field_id for f in body["data_fields"])
        assert any(k["id"] == kpi_id for k in body["kpis"])


class TestRunExecution:
    def test_run_fails_fast_without_data_source(self, client, db_session):
        """data_source_kind/data_source_id are required=True on the config
        schema, so a well-formed PUT /config can never omit them — the only
        way to reach this state is a config that predates a data-source
        connection (e.g. configured template but never picked a source).
        Simulate that directly against the installation row."""
        headers, org_id = _register_org(client, "No Source Org", "nosource@test.com")
        client.post(f"/api/apps/{APP_KEY}/install", headers=headers)

        installation = AppInstallationService.get_by_key(db_session, uuid.UUID(org_id), APP_KEY)
        installation.config = {"template_name": "kpi_update"}
        db_session.commit()

        client.put(
            f"/api/apps/{APP_KEY}/secret-config",
            json={"secret_config": {"waba_phone_number_id": "123", "waba_access_token": "tok"}},
            headers=headers,
        )
        _grant_entitlement(db_session, org_id)
        enable_resp = client.post(f"/api/apps/{APP_KEY}/enable", headers=headers)
        assert enable_resp.status_code == 200, enable_resp.text

        run = client.post(f"/api/apps/{APP_KEY}/run", json={}, headers=headers)
        assert run.status_code == 200
        assert run.json()["status"] == "failed"
        assert "data source" in run.json()["summary"].lower()

    def test_run_with_data_field_source_sends_to_recipients(self, client, db_session, fake_whatsapp):
        headers, org_id = _register_org(client, "Field Org", "field@test.com")
        field_id = _create_data_field_with_value(client, headers, "Outstanding Receivables", 42000)
        _install_and_configure(client, headers, org_id, db_session, data_source_kind="data_field", data_source_id=field_id)
        _add_recipient(client, headers)

        run = client.post(f"/api/apps/{APP_KEY}/run", json={}, headers=headers)
        assert run.status_code == 200, run.text
        result = run.json()["result"]
        assert result["sent"] == 1
        assert result["value"] == 42000
        assert len(fake_whatsapp) == 1
        assert fake_whatsapp[0]["template_variables"][1] == "42,000.00"

        logs = client.get(f"/api/apps/{APP_KEY}/send-logs", headers=headers)
        assert logs.json()["total"] == 1
        assert logs.json()["logs"][0]["delivery_status"] == "sent"
        assert logs.json()["logs"][0]["phone_masked"].endswith("1111")
        assert "999" not in logs.json()["logs"][0]["phone_masked"]

    def test_run_with_kpi_source_sends_to_recipients(self, client, db_session, fake_whatsapp):
        headers, org_id = _register_org(client, "KPI Org", "kpi@test.com")
        kpi_id = _create_kpi_with_value(client, headers, "Daily Revenue", 15000)
        _install_and_configure(client, headers, org_id, db_session, data_source_kind="kpi", data_source_id=kpi_id)
        _add_recipient(client, headers)

        run = client.post(f"/api/apps/{APP_KEY}/run", json={}, headers=headers)
        assert run.json()["result"]["sent"] == 1
        assert run.json()["result"]["value"] == 15000

    def test_run_with_no_data_yet_is_a_no_op(self, client, db_session):
        headers, org_id = _register_org(client, "Empty Org", "empty@test.com")
        resp = client.post("/api/data-fields", json={"name": "Unused Field"}, headers=headers)
        field_id = resp.json()["id"]
        _install_and_configure(client, headers, org_id, db_session, data_source_kind="data_field", data_source_id=field_id)
        _add_recipient(client, headers)

        run = client.post(f"/api/apps/{APP_KEY}/run", json={}, headers=headers)
        assert run.json()["status"] == "success"
        assert run.json()["result"]["sent"] == 0

    def test_threshold_gates_the_send(self, client, db_session, fake_whatsapp):
        headers, org_id = _register_org(client, "Threshold Org", "threshold@test.com")
        field_id = _create_data_field_with_value(client, headers, "Outstanding", 500)
        _install_and_configure(
            client, headers, org_id, db_session,
            data_source_kind="data_field", data_source_id=field_id,
            threshold_comparison="gte", threshold_value=1000,
        )
        _add_recipient(client, headers)

        run = client.post(f"/api/apps/{APP_KEY}/run", json={}, headers=headers)
        assert run.json()["result"]["sent"] == 0
        assert run.json()["result"]["threshold_met"] is False
        assert len(fake_whatsapp) == 0


class TestCrossTenantIsolation:
    def test_run_under_org_a_never_sees_org_b_data_or_recipients(self, client, db_session, fake_whatsapp):
        headers_a, org_a_id = _register_org(client, "Org A", "iso-notif-a@test.com")
        headers_b, org_b_id = _register_org(client, "Org B", "iso-notif-b@test.com")

        field_b = _create_data_field_with_value(client, headers_b, "Org B Field", 99999)
        _install_and_configure(client, headers_b, org_b_id, db_session, data_source_kind="data_field", data_source_id=field_b)
        _add_recipient(client, headers_b, name="Org B Recipient", phone="+919990002222")

        # Org A connects its own (empty) field — org A's data field, not org B's.
        resp = client.post("/api/data-fields", json={"name": "Org A Field"}, headers=headers_a)
        field_a = resp.json()["id"]
        _install_and_configure(client, headers_a, org_a_id, db_session, data_source_kind="data_field", data_source_id=field_a)

        run = client.post(f"/api/apps/{APP_KEY}/run", json={}, headers=headers_a)
        assert run.status_code == 200
        assert run.json()["result"]["sent"] == 0, "org A must not see org B's data or recipients"

        org_a_logs = db_session.query(WhatsAppSendLog).filter(
            WhatsAppSendLog.org_id == uuid.UUID(org_a_id)
        ).all()
        assert all(log.recipient_name != "Org B Recipient" for log in org_a_logs)

        org_a_recipients = db_session.query(WhatsAppRecipient).filter(
            WhatsAppRecipient.org_id == uuid.UUID(org_a_id)
        ).count()
        assert org_a_recipients == 0


class TestPerRecipientIdempotency:
    def test_second_run_in_same_period_does_not_resend(self, client, db_session, fake_whatsapp):
        headers, org_id = _register_org(client, "Retry Org", "retry-notif@test.com")
        field_id = _create_data_field_with_value(client, headers, "Outstanding", 5000)
        _install_and_configure(client, headers, org_id, db_session, data_source_kind="data_field", data_source_id=field_id)
        _add_recipient(client, headers)

        run1 = client.post(
            f"/api/apps/{APP_KEY}/run", json={"idempotency_key": f"k1-{uuid.uuid4()}"}, headers=headers
        )
        assert run1.json()["result"]["sent"] == 1

        run2 = client.post(
            f"/api/apps/{APP_KEY}/run", json={"idempotency_key": f"k2-{uuid.uuid4()}"}, headers=headers
        )
        assert run2.json()["result"]["sent"] == 0
        assert run2.json()["result"]["skipped_duplicate"] == 1

        logs = client.get(f"/api/apps/{APP_KEY}/send-logs", headers=headers)
        sent_logs = [l for l in logs.json()["logs"] if l["delivery_status"] == "sent"]
        assert len(sent_logs) == 1, "retried run must not create a second 'sent' record"
        assert len(fake_whatsapp) == 1


class TestSuppression:
    def test_suppressed_number_is_never_messaged(self, client, db_session, fake_whatsapp):
        headers, org_id = _register_org(client, "Suppress Org", "suppress-notif@test.com")
        field_id = _create_data_field_with_value(client, headers, "Outstanding", 5000)
        _install_and_configure(client, headers, org_id, db_session, data_source_kind="data_field", data_source_id=field_id)
        _add_recipient(client, headers, phone="+919990009999")

        resp = client.post(
            f"/api/apps/{APP_KEY}/suppressions",
            json={"phone": "+919990009999", "reason": "customer_requested"},
            headers=headers,
        )
        assert resp.status_code == 201

        run = client.post(f"/api/apps/{APP_KEY}/run", json={}, headers=headers)
        result = run.json()["result"]
        assert result["sent"] == 0
        assert result["skipped_suppressed"] == 1
        assert len(fake_whatsapp) == 0

        logs = client.get(f"/api/apps/{APP_KEY}/send-logs", headers=headers).json()["logs"]
        assert logs[0]["delivery_status"] == "skipped_suppressed"

        resp = client.delete(f"/api/apps/{APP_KEY}/suppressions/+919990009999", headers=headers)
        assert resp.status_code == 204
        resp2 = client.delete(f"/api/apps/{APP_KEY}/suppressions/+919990009999", headers=headers)
        assert resp2.status_code == 404


class TestRecipientsCsvImport:
    def test_import_csv_creates_recipients(self, client):
        headers, _ = _register_org(client, "CSV Org", "csv-notif@test.com")
        client.post(f"/api/apps/{APP_KEY}/install", headers=headers)

        csv_content = (
            "name,phone,notes\n"
            "Bulk Recipient 1,+919990004444,VIP customer\n"
            "Bulk Recipient 2,+919990005555,\n"
            ",missing-name,oops\n"
        )
        files = {"file": ("recipients.csv", csv_content, "text/csv")}
        resp = client.post(f"/api/apps/{APP_KEY}/recipients/import-csv", files=files, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["imported"] == 2
        assert len(body["errors"]) == 1

        listing = client.get(f"/api/apps/{APP_KEY}/recipients", headers=headers)
        assert listing.json()["total"] == 2
