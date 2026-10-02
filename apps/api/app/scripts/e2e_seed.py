"""Signs in one instructor for the Playwright smoke suite, without Auth0.

Prints the raw session token that Playwright sets as the __Host-session cookie.
The row is made by create_session, the same function the Auth0 callback uses, so
every request in the suite passes through the real session check. No HTTP route
reaches this: running it needs a shell in the API container.
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime

from config import ENVIRONMENT
from db import async_session
from models import User, UserRoleEnum
from services import create_session


async def seed() -> str:
    async with async_session() as db:
        user = User(
            id=uuid.uuid4(),
            email="e2e-instructor@example.test",
            # Not a shape Auth0 issues, so this row can never bind to a real login.
            auth0_sub="e2e|instructor",
            display_name="E2E Instructor",
            role=UserRoleEnum.instructor,
            first_login_at=datetime.now(UTC),
        )
        db.add(user)
        await db.flush()
        return await create_session(db, user.id)


def main() -> None:
    if ENVIRONMENT != "dev":
        sys.exit("e2e_seed only runs with ENVIRONMENT=dev.")
    print(asyncio.run(seed()))


if __name__ == "__main__":
    main()
