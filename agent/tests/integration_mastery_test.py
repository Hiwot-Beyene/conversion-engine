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
async def test_api_failure_handling_with_retries():
    """Verifies that API failures trigger retries (via tenacity check logically)."""
    client = HubSpotClient()
    
    # Simulate a transient 500 error then success
    mock_fail = MagicMock()
    mock_fail.status_code = 500
    mock_fail.text = "Transient Error"
    
    mock_success = MagicMock()
    mock_success.status_code = 200
    mock_success.json.return_value = {"total": 0}
    
    # We'll mock the post to fail twice then succeed
    side_effects = [mock_fail, mock_fail, mock_success]
    
    with patch("httpx.AsyncClient.post", AsyncMock(side_effect=side_effects)):
        # Since we use tenacity, it should eventually succeed
        result = await client.create_or_update_contact("fail@test.com", {})
        assert result["success"] is True

@pytest.mark.asyncio
async def test_icp_segmentation_logic():
    """Verifies that sync_enrichment_data correctly classifies Enterprise vs Mid-Market leads."""
    client = HubSpotClient()
    
    # Mock create_or_update call
    client.create_or_update_contact = AsyncMock()
    
    # 1. Enterprise Test
    signals_ent = {"crunchbase": {"data": {"employee_count": 1000, "name": "Big Corp"}}}
    await client.sync_enrichment_data("ent@corp.com", signals_ent)
    
    args, kwargs = client.create_or_update_contact.call_args
    assert args[1]["icp_segment"] == "Enterprise Fit"
    
    # 2. Mid-Market Test
    signals_mid = {"crunchbase": {"data": {"employee_count": 100, "name": "Growth Co"}}}
    await client.sync_enrichment_data("mid@growth.com", signals_mid)
    
    args, kwargs = client.create_or_update_contact.call_args
    assert args[1]["icp_segment"] == "Mid-Market / High Fit"
