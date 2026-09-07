import argparse
import asyncio
import sys
import uuid

from auth import delete_auth0_user, find_auth0_user_id_by_email, invite_user
from db import async_session
from models import User, UserRoleEnum
from services import normalize_email


# Helper function to seed users into the database. Only for dev / seeding root admin.
async def add_user(email: str, role: str) -> None:
    """Allowlists a user before their first Auth0 login.

    This cannot go through services.create_user - that one requires an acting
    user and refuses to produce a root_admin, which is exactly what this script
    exists to seed. It shares create_user's normalisation instead, because a row
    written here in a different case than Auth0 sends is a row nobody can log
    into."""
    email = normalize_email(email)

    # Check if user already exists in Auth0, ensure idempotency across different developers.
    auth0_user_id = await find_auth0_user_id_by_email(email)
    newly_invited = auth0_user_id is None
    if newly_invited:
        # If it is new user without Auth0 account, invite them and send invitation email.
        auth0_user_id = await invite_user(email)
    else:
        print(f"Auth0 already has a credential for {email} - reusing it instead of re-inviting.")

    async with async_session() as db:
        # If user already exists in Auth0 create a row in Local DB to insert them with the updated Auth0_Sub
        user = User(id=uuid.uuid4(), email=email, role=UserRoleEnum(role), auth0_sub=auth0_user_id)
        db.add(user)
        try:
            await db.commit()
        except Exception:
            # Rollback
            if newly_invited:
                await db.rollback()
                await delete_auth0_user(auth0_user_id)
            raise
        print(f"Provisioned {email} as {role} ({user.id})")
        if newly_invited:
            print(f"Auth0 emailed {email} a link to set their password.")


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
