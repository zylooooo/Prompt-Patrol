import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db import get_db
from main import app
from models import Base


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # SQLite ignores foreign keys unless asked. Postgres does not, so without
    # this a test can insert a row pointing at a user that was never created,
    # pass, and describe something the real database would reject.
    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    """`fastapi.testclient.TestClient` runs the ASGI app on a fresh
    thread+event loop for every single call (see starlette.testclient's
    `_portal_factory`), while `db_session` is an asyncio-loop-bound aiosqlite
    connection created on pytest-asyncio's loop. Mixing them raises
    `RuntimeError: ... attached to a different loop` (deterministically on
    CI's Linux runner, intermittently elsewhere) the moment a route actually
    awaits a query. httpx.AsyncClient over ASGITransport runs the app
    in-process on the current loop instead, so there is never a second loop
    to mismatch against."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        ac.app = app
        yield ac
    app.dependency_overrides.clear()
