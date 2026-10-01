import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.conftest import TEST_DB_URL

from models import Base, UserRoleEnum, UserStatusEnum
from services import authenticate_session


# Same reason as test_provision_user: seed() opens its own session via
# db.async_session, so it gets a throwaway engine patched in.
@pytest_asyncio.fixture
async def _e2e_seed_module(monkeypatch):
    from scripts import e2e_seed

    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(e2e_seed, "async_session", session_factory)

    yield e2e_seed, session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_seed_returns_a_token_for_an_active_named_instructor(_e2e_seed_module):
    e2e_seed, session_factory = _e2e_seed_module

    token = await e2e_seed.seed()

    async with session_factory() as db:
        session = await authenticate_session(db, token)
    assert session.user.role is UserRoleEnum.instructor
    assert session.user.status is UserStatusEnum.active
    assert session.user.display_name is not None


def test_main_refuses_outside_dev(monkeypatch):
    from scripts import e2e_seed

    monkeypatch.setattr(e2e_seed, "ENVIRONMENT", "prod")

    with pytest.raises(SystemExit) as exc:
        e2e_seed.main()
    assert exc.value.code not in (0, None)
