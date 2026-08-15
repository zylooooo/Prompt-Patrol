import argparse
import asyncio
import sys
import uuid

from db import async_session
from models import User, UserRoleEnum


# Helper function to seed users into the database. Only for dev / seeding root admin.
async def add_user(email: str, role: str) -> None:
    """Allowlists a user before their first Entra login. entra_oid is left
    null; resolve_or_bind_user fills it in on that first successful login."""
    async with async_session() as db:
        user = User(id=uuid.uuid4(), email=email, role=UserRoleEnum(role))
        db.add(user)
        await db.commit()
        print(f"Provisioned {email} as {role} ({user.id})")


async def delete_user(user_id: str) -> None:
    """Hard delete a user from the database."""
    async with async_session() as db:
        user = await db.get(User, uuid.UUID(user_id))
        if user is None:
            print(f"No user found with ID {user_id}")
            return
        await db.delete(user)
        await db.commit()
        print(f"Deleted user {user.email} ({user.id})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision or remove Prompt Patrol users.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("email")
    add_parser.add_argument("role", choices=[r.value for r in UserRoleEnum])

    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("user_id")

    args = parser.parse_args()
    if args.command == "add":
        asyncio.run(add_user(args.email, args.role))
    elif args.command == "delete":
        asyncio.run(delete_user(args.user_id))


## Can consider deleting this whole file in production after seeding the root admin.
if __name__ == "__main__":
    sys.path.insert(0, ".")
    main()
