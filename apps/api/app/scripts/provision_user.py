import argparse
import asyncio
import sys
import uuid

from db import async_session
from models import User, UserRoleEnum
from services import normalize_email


# Helper function to seed users into the database. Only for dev / seeding root admin.
async def add_user(email: str, role: str) -> None:
    """Allowlists a user before their first Entra login. entra_oid is left
    null; resolve_or_bind_user fills it in on that first successful login.

    This cannot go through services.create_user - that one requires an acting
    user and refuses to produce a root_admin, which is exactly what this script
    exists to seed. It shares create_user's normalisation instead, because a row
    written here in a different case than Entra sends is a row nobody can log
    into."""
    async with async_session() as db:
        email = normalize_email(email)
        user = User(id=uuid.uuid4(), email=email, role=UserRoleEnum(role))
        db.add(user)
        await db.commit()
        print(f"Provisioned {email} as {role} ({user.id})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the first Prompt Patrol root admin.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("email")
    add_parser.add_argument("role", choices=[r.value for r in UserRoleEnum])

    args = parser.parse_args()
    if args.command == "add":
        asyncio.run(add_user(args.email, args.role))


## Can consider deleting this whole file in production after seeding the root admin.
if __name__ == "__main__":
    sys.path.insert(0, ".")
    main()
