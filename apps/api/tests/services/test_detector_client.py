from unittest.mock import AsyncMock, patch

import httpx
import pytest

import services.detector_client as detector_client


async def _health_seeing(**response_kwargs):
    response = httpx.Response(request=httpx.Request("GET", "http://detector/health"), **response_kwargs)
    with patch.object(detector_client._client, "get", new=AsyncMock(return_value=response)):
        return await detector_client.health()


@pytest.mark.asyncio
async def test_a_200_means_ready():
    assert await _health_seeing(status_code=200, json={"status": "ready"}) == "ready"


@pytest.mark.asyncio
async def test_a_detector_still_loading_is_not_reported_as_broken():
    """The distinction the whole status badge exists for: this one clears on its
    own in under a minute, so it must not read the same as a dead service."""
    assert await _health_seeing(status_code=503, json={"status": "loading"}) == "loading"


@pytest.mark.asyncio
async def test_a_failed_load_is_unavailable():
    assert await _health_seeing(status_code=503, json={"status": "failed"}) == "unavailable"


@pytest.mark.asyncio
async def test_a_body_that_is_not_json_is_unavailable():
    assert await _health_seeing(status_code=503, text="Bad Gateway") == "unavailable"


@pytest.mark.asyncio
async def test_an_unreachable_detector_is_unavailable():
    with patch.object(
        detector_client._client,
        "get",
        new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
    ):
        assert await detector_client.health() == "unavailable"


@pytest.mark.asyncio
async def test_a_hung_detector_does_not_hold_the_badge_open():
    """Scoring gets 10s; the badge polls, so it gives up quickly instead."""
    with patch.object(
        detector_client._client,
        "get",
        new=AsyncMock(side_effect=httpx.ReadTimeout("timed out")),
    ):
        assert await detector_client.health() == "unavailable"
