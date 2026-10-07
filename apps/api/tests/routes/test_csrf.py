"""State-changing requests must come from our own origin (DECISION LOG [0.25.0])."""

import pytest

from config import FRONTEND_URL

OWN_ORIGIN = FRONTEND_URL.rstrip("/")


@pytest.mark.parametrize(
    ("headers", "allowed"),
    [
        ({"Sec-Fetch-Site": "same-origin"}, True),
        ({"Sec-Fetch-Site": "none"}, True),
        ({"Sec-Fetch-Site": "same-site"}, False),
        ({"Sec-Fetch-Site": "cross-site"}, False),
        # Sec-Fetch-Site wins over a matching Origin.
        ({"Sec-Fetch-Site": "cross-site", "Origin": OWN_ORIGIN}, False),
        ({"Origin": OWN_ORIGIN}, True),
        ({"Origin": "https://evil.example"}, False),
        ({"Origin": OWN_ORIGIN + ".attacker.com"}, False),
        ({}, False),
    ],
)
@pytest.mark.asyncio
async def test_a_post_is_allowed_only_from_our_own_origin(client, headers, allowed):
    client.headers.pop("Sec-Fetch-Site")
    response = await client.post("/api/auth/logout", headers=headers, follow_redirects=False)

    if allowed:
        assert response.status_code == 303
    else:
        assert response.status_code == 403
        assert response.json()["error"] == "forbidden"
        assert response.json()["request_id"] != "-"


@pytest.mark.asyncio
async def test_a_cross_site_get_is_not_refused(client):
    response = await client.get("/api/no-such-route", headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 404
