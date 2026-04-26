import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from agent.integrations.hubspot_mcp import HubSpotClient, HubSpotError
from agent.channels.cal_client import CalClient, CalError

@pytest.mark.asyncio
async def test_hubspot_idempotency_safeguard():
    """Verifies that HubSpot sync uses search before update to ensure idempotency."""
    client = HubSpotClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"total": 1, "results": [{"id": "123"}]}
    
    with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_resp)) as mock_post:
        with patch("httpx.AsyncClient.patch", AsyncMock(return_value=mock_resp)) as mock_patch:
            await client.create_or_update_contact("test@example.com", {"company": "Test Co"})
            
            # Assert search was called
            assert mock_post.called
            # Assert patch was called (idempotent update)
            assert mock_patch.called

@pytest.mark.asyncio
async def test_cal_flatten_slots_response():
    """Cal v2 /slots returns date-keyed arrays, not data.slots."""
    raw = {
        "2050-09-05": [
            {"start": "2050-09-05T10:00:00.000+02:00"},
            "2050-09-05T11:00:00.000+02:00",
        ],
        "2050-09-06": [{"start": "2050-09-06T09:00:00.000+02:00"}],
    }
    flat = CalClient._flatten_slots_data(raw)
    assert flat[0].startswith("2050-09-05")
    assert len(flat) == 3


@pytest.mark.asyncio
async def test_cal_booking_idempotency():
    """Verifies that Cal.com client blocks duplicate bookings for the same time slot."""
    client = CalClient()
    
    # 1. Mock existing booking found
    mock_search_resp = MagicMock()
    mock_search_resp.status_code = 200
    mock_search_resp.json.return_value = {"data": [{"id": 999, "start": "2026-05-01T10:00:00Z"}]}
    
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_search_resp)):
        res = await client.book_meeting("Test", "test@example.com", "2026-05-01T10:00:00Z")
        
        assert res["success"] is True
        assert res["booking_id"] == 999
        assert res["status"] == "existing"

@pytest.mark.asyncio
async def test_cal_booking_idempotency_skips_non_dict_rows():
    """List bookings may return strings or mixed lists — must not crash; proceeds to create."""
    client = CalClient()
    client.event_type_id = "123"
    mock_search_resp = MagicMock()
    mock_search_resp.status_code = 200
    mock_search_resp.json.return_value = {"data": ["uid-only-row", {"id": 1, "start": "2026-05-02T10:00:00Z"}]}

    mock_create_resp = MagicMock()
    mock_create_resp.status_code = 201
    mock_create_resp.json.return_value = {"data": {"id": 42, "uid": "abc"}}

    async def mock_get(*args, **kwargs):
        return mock_search_resp

    async def mock_post(*args, **kwargs):
        return mock_create_resp

    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=mock_get)):
        with patch("httpx.AsyncClient.post", AsyncMock(side_effect=mock_post)):
            res = await client.book_meeting("Acme", "test@example.com", "2026-05-01T10:00:00Z")

    assert res["success"] is True
    assert res["status"] == "created"
    assert res["booking_id"] == 42

@pytest.mark.asyncio
async def test_api_failure_handling_with_retries():
    """Non-2xx HubSpot responses raise HubSpotError so tenacity can retry / fail closed."""
    client = HubSpotClient()
    mock_fail = MagicMock()
    mock_fail.status_code = 500
    mock_fail.text = "Transient Error"

    with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_fail)):
        with pytest.raises(HubSpotError):
            await client.create_or_update_contact("fail@test.com", {"company": "Co"})


@pytest.mark.asyncio
async def test_icp_segmentation_logic():
    """sync_enrichment_data passes icp_segment derived from firmographics into contact properties."""
    client = HubSpotClient()
    client.create_or_update_contact = AsyncMock(return_value={"success": True, "data": {"id": "1"}})
    client._create_note_engagement = AsyncMock(return_value={"ok": True})

    signals_ent = {"crunchbase": {"data": {"employee_count": 1000, "name": "Big Corp"}}}
    await client.sync_enrichment_data("ent@corp.com", signals_ent)
    ent_props = client.create_or_update_contact.call_args_list[0][0][1]
    # Default: ICP fit is rolled into jobtitle when custom HubSpot properties are off.
    assert ent_props.get("icp_segment") == "Enterprise Fit" or "Enterprise Fit" in (
        ent_props.get("jobtitle") or ""
    )

    signals_mid = {"crunchbase": {"data": {"employee_count": 100, "name": "Growth Co", "funding_amount_usd": 0}}}
    await client.sync_enrichment_data("mid@growth.com", signals_mid)
    mid_props = client.create_or_update_contact.call_args_list[1][0][1]
    assert mid_props.get("icp_segment") == "Mid-Market / High Fit" or "Mid-Market / High Fit" in (
        mid_props.get("jobtitle") or ""
    )
