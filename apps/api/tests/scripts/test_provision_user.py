import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base, User


# provision_user.add_user() opens its own session via db.async_session rather
# than taking one as an argument (it's a standalone CLI script, not a request
# handler), so it gets its own throwaway engine here instead of the shared
# db_session fixture.
@pytest_asyncio.fixture
async def _provision_user_module(monkeypatch):
    from scripts import provision_user

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(provision_user, "async_session", session_factory)

    yield provision_user, session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_add_user_invites_when_auth0_has_no_existing_credential(_provision_user_module, monkeypatch):
    provision_user, session_factory = _provision_user_module
    invited = []

    async def fake_find(email):
        return None

    async def fake_invite(email):
        invited.append(email)
        return "auth0|fresh-id"

    monkeypatch.setattr(provision_user, "find_auth0_user_id_by_email", fake_find)
    monkeypatch.setattr(provision_user, "invite_user", fake_invite)

    await provision_user.add_user("fresh@smu.edu.sg", "root_admin")

    assert invited == ["fresh@smu.edu.sg"]
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == "fresh@smu.edu.sg"))).scalar_one()
        assert user.auth0_sub == "auth0|fresh-id"


@pytest.mark.asyncio
async def test_add_user_reuses_existing_auth0_credential(_provision_user_module, monkeypatch):
    # The idempotency case: re-running against an email Auth0 already knows
    # (a re-seed after a local DB reset) must not re-invite.
    provision_user, session_factory = _provision_user_module
    invited = []

    async def fake_find(email):
        return "auth0|existing-id"

    async def fake_invite(email):
        invited.append(email)
        return "auth0|should-not-be-used"

    monkeypatch.setattr(provision_user, "find_auth0_user_id_by_email", fake_find)
    monkeypatch.setattr(provision_user, "invite_user", fake_invite)

    await provision_user.add_user("reseeded@smu.edu.sg", "root_admin")

    assert invited == []
    async with session_factory() as db:
        user = (await db.execute(select(User).where(User.email == "reseeded@smu.edu.sg"))).scalar_one()
        assert user.auth0_sub == "auth0|existing-id"
