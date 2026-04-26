import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.config import Environment  # noqa: F401 — used in cal webhook test
from agent.integrations.hubspot_mcp import HubSpotClient, HubSpotError
from agent.webhooks import cal_webhook


def test_cal_webhook_hmac_accepts_valid_signature():
    body = b'{"triggerEvent":"BOOKING_CREATED"}'
    secret = "test-secret"
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    class _S:
        CALCOM_WEBHOOK_SECRET = secret
        ENVIRONMENT = Environment.DEVELOPMENT

    with patch.object(cal_webhook, "settings", _S()):
        assert cal_webhook._verify_cal_signature(body, digest)
        assert cal_webhook._verify_cal_signature(body, f"sha256={digest}")
        assert not cal_webhook._verify_cal_signature(body, "deadbeef")


@pytest.mark.asyncio
async def test_hubspot_create_strips_missing_properties_and_retries():
    """Portal returns PROPERTY_DOESNT_EXIST — client drops bad keys and PATCH succeeds."""
    from agent.integrations.hubspot_mcp import HubSpotClient

    client = HubSpotClient()
    search_ok = MagicMock()
    search_ok.status_code = 200
    search_ok.json.return_value = {"total": 1, "results": [{"id": "99"}]}

    bad = MagicMock()
    bad.status_code = 400
    bad.text = (
        '{"errors":[{"code":"PROPERTY_DOESNT_EXIST",'
        '"context":{"propertyName":["crunchbase_id"]}}]}'
    )

    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"id": "99"}

    patch_mock = AsyncMock(side_effect=[bad, ok])

    with patch(
        "agent.integrations.hubspot_mcp._hubspot_prop_allowlist",
        return_value=frozenset({"company", "crunchbase_id"}),
    ):
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=search_ok)):
            with patch("httpx.AsyncClient.patch", patch_mock):
                out = await client.create_or_update_contact(
                    "x@y.com",
                    {"company": "Co", "crunchbase_id": "abc"},
                )
    assert out.get("success") is True
    assert patch_mock.call_count == 2
    second_props = patch_mock.call_args_list[1][1]["json"]["properties"]
    assert "crunchbase_id" not in second_props
    assert second_props.get("company") == "Co"


@pytest.mark.asyncio
async def test_hubspot_create_raises_after_http_errors():
    client = HubSpotClient()
    mock_fail = MagicMock()
    mock_fail.status_code = 500
    mock_fail.text = "Transient"

    with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_fail)):
        with pytest.raises(HubSpotError):
            await client.create_or_update_contact("fail@test.com", {"company": "Acme"})


@pytest.mark.asyncio
async def test_email_client_suppressed_under_kill_switch(monkeypatch):
    from agent.channels import email_client as ec

    mock_s = MagicMock()
    mock_s.outbound_is_suppressed = lambda: True
    mock_s.RESEND_API_KEY = "k"
    mock_s.RESEND_FROM_EMAIL = "from@example.com"
    monkeypatch.setattr(ec, "settings", mock_s)
    client = ec.EmailClient()
    out = await client.send_email(to="a@b.com", subject="Hi", html="<p>x</p>")
    assert out.get("suppressed") is True


@pytest.mark.asyncio
async def test_sms_client_suppressed_under_kill_switch(monkeypatch):
    from agent.channels import sms_client as sc

    mock_s = MagicMock()
    mock_s.outbound_is_suppressed = lambda: True
    mock_s.AT_USERNAME = "u"
    mock_s.AT_API_KEY = "k"
    mock_s.AT_SHORT_CODE = "12345"
    mock_s.AT_SENDER_ID = None
    monkeypatch.setattr(sc, "settings", mock_s)
    client = sc.SMSClient()
    out = await client.send_warm_lead_sms(to="+15550001", message="hi")
    assert out.get("suppressed") is True
