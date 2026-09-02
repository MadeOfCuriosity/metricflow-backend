"""Fernet-at-rest plumbing for OrgAppInstallation.secret_config_encrypted.

Reuses the same app.core.encryption helpers as Integration's OAuth/API-key
storage. Unlike Integration (one encrypted column per credential), an app's
secret config is an arbitrary dict shaped by its config_schema, so the whole
dict is JSON-serialized and encrypted as a single blob. Decrypted plaintext
must never reach the frontend — callers return `secret_config_status()`
(configured/last-4 only) instead.
"""
import json

from app.core.encryption import encrypt_value, decrypt_value
from app.services.apps import get_app
from app.services.apps.base import AppConfigField


class SecretConfigError(Exception):
    """Raised for invalid secret-config writes (unknown key, missing required field)."""


def get_secret_config(installation) -> dict:
    """Decrypt and return the plaintext secret config dict. Callers must
    treat this as sensitive — never log it, never return it verbatim over
    the API. Only the runner (at send time) and the set/status helpers below
    should call this."""
    if not installation.secret_config_encrypted:
        return {}
    return json.loads(decrypt_value(installation.secret_config_encrypted))


def set_secret_config(db, installation, values: dict) -> "OrgAppInstallation":
    """Merge `values` into the installation's encrypted secret config and
    persist. Only keys declared `secret=True` on the app's config_schema are
    accepted; unknown keys are rejected rather than silently dropped so a
    typo'd field name doesn't silently fail to configure the send path.
    Blank/None values are ignored (they don't clear an already-configured
    secret) — use a distinct "clear" action if that's ever needed."""
    app = get_app(installation.app_key)
    secret_fields: dict[str, AppConfigField] = {f.key: f for f in app.config_schema if f.secret}

    unknown = set(values.keys()) - set(secret_fields.keys())
    if unknown:
        raise SecretConfigError(f"Unknown secret config field(s): {', '.join(sorted(unknown))}")

    merged = get_secret_config(installation)
    for key, value in values.items():
        if value in (None, ""):
            continue
        merged[key] = value

    missing = [f.key for f in secret_fields.values() if f.required and not merged.get(f.key)]
    if missing:
        raise SecretConfigError(f"Missing required secret config field(s): {', '.join(missing)}")

    installation.secret_config_encrypted = encrypt_value(json.dumps(merged))
    db.commit()
    db.refresh(installation)
    return installation


def secret_config_status(installation) -> dict:
    """Masked view safe to return over the API: for each declared secret
    field, whether it's configured and (if so) its last 4 characters —
    never the plaintext value."""
    app = get_app(installation.app_key)
    secrets = get_secret_config(installation)
    status = {}
    for f in app.config_schema:
        if not f.secret:
            continue
        value = secrets.get(f.key)
        status[f.key] = {
            "configured": bool(value),
            "last4": value[-4:] if value and len(value) >= 4 else None,
        }
    return status
