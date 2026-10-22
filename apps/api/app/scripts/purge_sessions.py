import asyncio
import logging
import sys

from config import configure_logging
from db import async_session
from services import purge_expired_sessions

logger = logging.getLogger(__name__)


# Daily one-off ECS task: deletes session rows past the retention window.
async def main() -> None:
    async with async_session() as db:
        removed = await purge_expired_sessions(db)
    logger.info("Purged %d expired session rows.", removed)


if __name__ == "__main__":
    sys.path.insert(0, ".")
    configure_logging()
    asyncio.run(main())
