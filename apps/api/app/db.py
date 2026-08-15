import logging
from collections.abc import AsyncGenerator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DB_URL

logger = logging.getLogger(__name__)

engine = create_async_engine(DB_URL, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


# Provides an async database session which is automatically closed after the request is done.
async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session() as session:
        try:
            yield session
        except SQLAlchemyError:
            logger.exception("Database error during request.")
            raise
