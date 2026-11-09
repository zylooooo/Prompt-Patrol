import asyncio
import logging
import sys

from config import configure_logging
from db import async_session
from services import purge_expired_checks

logger = logging.getLogger(__name__)


# Daily one-off ECS task: deletes check history past the retention window.
async def main() -> None:
    async with async_session() as db:
        checks, batches = await purge_expired_checks(db)
    logger.info("Purged %d checks and %d batches past retention.", checks, batches)


if __name__ == "__main__":
    sys.path.insert(0, ".")
    configure_logging()
    asyncio.run(main())
