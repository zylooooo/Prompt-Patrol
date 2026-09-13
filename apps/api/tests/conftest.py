import os

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base

# Deliberately independent of the app's own DB_URL (which in local dev points
# at the "postgres" compose hostname, unreachable from a host-run pytest).
# CI sets TEST_DB_URL to its disposable Postgres service container; anyone
# else gets the sqlite fallback for a quick run with nothing else up.
TEST_DB_URL = os.environ.get("TEST_DB_URL", "sqlite+aiosqlite:///:memory:")


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DB_URL)

    # SQLite ignores foreign keys unless asked; Postgres enforces them
    # natively.
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _enforce_foreign_keys(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        # drop_all first: CI's Postgres service container is one long-lived
        # database shared across every test in the run, unlike a fresh
        # in-memory SQLite file per test.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()
