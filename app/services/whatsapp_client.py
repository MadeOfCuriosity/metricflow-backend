"""Thin client for sending messages via an org's own WhatsApp Business
Account (WABA) through Meta's Graph API. Every installing org supplies its
own WABA phone-number-id + access token (Step 3 secret config) — this app
never sends through a shared Visualize-owned number, containing ban risk to
one org and keeping the sender recognizable to the customer.

Outbound calls go to graph.facebook.com. Confirm the deployed backend's
egress (NAT/VPC-connector) actually reaches that host before relying on this
in production — a private-subnet backend with no working NAT route fails
every send here without a loud error at deploy time.
"""
import logging

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v18.0"
GRAPH_API_BASE = "https://graph.facebook.com"


class WhatsAppSendError(Exception):
    """Raised when the Graph API rejects a send. Message is safe to log —
    callers must not include the access token or raw response body if it
    might echo the token back."""


def _messages_url(phone_number_id: str) -> str:
    return f"{GRAPH_API_BASE}/{GRAPH_API_VERSION}/{phone_number_id}/messages"


def send_template_message(
    *,
    phone_number_id: str,
    access_token: str,
    to_phone: str,
    template_name: str,
    template_namespace: str | None,
    template_variables: list[str],
    language_code: str = "en_US",
) -> str:
    """Send an approved WhatsApp utility template. Returns the provider
    message id on success; raises WhatsAppSendError on failure. Never logs
    `access_token` or the full `to_phone`."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(v)} for v in template_variables],
                }
            ] if template_variables else [],
        },
    }
    if template_namespace:
        payload["template"]["namespace"] = template_namespace

    return _post(phone_number_id, access_token, payload, to_phone)


def _post(phone_number_id: str, access_token: str, payload: dict, to_phone: str) -> str:
    masked = f"***{to_phone[-4:]}" if to_phone and len(to_phone) >= 4 else "***"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                _messages_url(phone_number_id),
                headers={"Authorization": f"Bearer {access_token}"},
                json=payload,
            )
    except httpx.HTTPError as e:
        logger.error(f"WhatsApp send network error to {masked}: {type(e).__name__}")
        raise WhatsAppSendError(f"Network error contacting WhatsApp Graph API: {type(e).__name__}") from e

    if resp.status_code >= 400:
        # Meta error bodies don't echo the token but may reflect `to`; keep
        # the logged detail generic rather than dumping the raw body.
        logger.error(f"WhatsApp send failed to {masked}: HTTP {resp.status_code}")
        try:
            detail = resp.json().get("error", {}).get("message", "unknown error")
        except Exception:
            detail = f"HTTP {resp.status_code}"
        raise WhatsAppSendError(detail)

    data = resp.json()
    messages = data.get("messages") or []
    if not messages:
        raise WhatsAppSendError("WhatsApp API returned no message id")
    return messages[0].get("id", "")
