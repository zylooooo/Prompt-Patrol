"""Every error is the contract's `Error` body, and validation is 400 (DECISION LOG [0.23.0])."""

import uuid
from unittest.mock import patch

import pytest

from models import User, UserRoleEnum
from services import create_session


@pytest.mark.asyncio
async def test_an_unknown_route_is_an_error_body(client):
    response = await client.get("/api/no-such-route")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    assert response.json()["request_id"] != "-"


@pytest.mark.asyncio
async def test_validation_names_the_field_but_never_echoes_the_value(client):
    response = await client.get("/api/auth/login", params={"force_account_chooser": "student-answer-text"})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert "force_account_chooser" in response.json()["message"]
    assert "student-answer-text" not in response.text


@pytest.mark.asyncio
async def test_an_unhandled_exception_is_a_500_with_a_request_id(client):
    with patch("routes.auth_routes.oauth.auth0.authorize_redirect", side_effect=RuntimeError("secret detail")):
        response = await client.get("/api/auth/login")

    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"
    assert response.json()["request_id"] != "-"
    assert "secret detail" not in response.text


@pytest.mark.asyncio
async def test_a_validator_message_drops_the_pydantic_prefix(client, db_session):
    # "display_name: Value error, display_name cannot be blank" read as a bug report.
    me = User(id=uuid.uuid4(), email="me@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(me)
    await db_session.commit()
    client.cookies.set("__Host-session", await create_session(db_session, me.id))

    response = await client.patch(f"/api/users/{me.id}", json={"display_name": "<>"})

    assert response.status_code == 400
    assert response.json()["message"] == "display_name: display_name cannot be blank"
