# Prompt Patrol — API

FastAPI + SQLAlchemy + Postgres, with Microsoft Entra ID sign-in. See the
[repo README](../../README.md) for running the full stack; this file covers the
backend only.

## Migrations

```bash
docker exec prompt-patrol-api alembic upgrade head
```

Creates the `users`/`sessions` tables. Run it inside the container so it uses the
container's `DB_URL` — that way there's no host/`localhost` hostname mismatch to
work around.

## Provisioning accounts

There is no self-service signup, so every account has to be allowlisted before
its first sign-in.

```bash
docker exec prompt-patrol-api sh -c "cd /app && python -m scripts.provision_user add <your-dev-tenant-email> root_admin"
```

Must be run as `-m scripts.provision_user`, not
`python scripts/provision_user.py` — the latter fails with
`ModuleNotFoundError: No module named 'db'`, since Python puts the script's own
folder on `sys.path` instead of the app root.

## Signing in

**Microsoft Entra ID is the only way in**, in every environment including local
development. Fill in `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`,
`ENTRA_REDIRECT_URI` and `SESSION_SECRET`. All five are required; a partial fill is a
startup error rather than a half-working OAuth client, and a blank fill is refused
outright rather than booting an app nobody can sign into.

The flow is Authorization Code + PKCE (`S256`) against a tenant-scoped discovery URL,
so only identities in your own Entra tenant can reach the login form. Roles never come
from Entra — they are read from the local `users` row, which must be provisioned above
before the first sign-in.

> **The password-less local dev login has been removed.** `DEV_AUTH_ENABLED` and
> `/api/auth/dev/*` no longer exist; the flag is ignored if left in a `.env`. It issued
> a real session to any provisioned email with no identity check, and once Entra was
> live it was pure attack surface. `tests/routes/test_auth.py` has a regression test
> asserting those paths stay gone. Recovering an environment now means provisioning
> through `scripts.provision_user`, not bypassing sign-in.

Use Chrome or Firefox — the session cookie is `Secure` + `__Host-`-prefixed even
locally, and Safari won't store it over plain HTTP.
