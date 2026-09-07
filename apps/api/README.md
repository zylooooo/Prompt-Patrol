# Prompt Patrol — API

FastAPI + SQLAlchemy + Postgres, with Auth0 sign-in. See the
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
its first sign-in. This also creates their Auth0 credential and Auth0
emails them a one-time link to set their own password directly upon first log in.

```bash
docker exec prompt-patrol-api sh -c "cd /app && python -m scripts.provision_user add <your-dev-tenant-email> root_admin"
```

Must be run as `-m scripts.provision_user`, not
`python scripts/provision_user.py` — the latter fails with
`ModuleNotFoundError: No module named 'db'`, since Python puts the script's own
folder on `sys.path` instead of the app root.

## Signing in

**Auth0 is the only way in**, in every environment including local development. Fill
in `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_REDIRECT_URI` and
`SESSION_SECRET`. All five are required; a partial fill is a startup error rather than
a half-working OAuth client, and a blank fill is refused outright rather than booting
an app nobody can sign into.

The flow is Authorization Code + PKCE (`S256`) against Auth0's discovery document.
The Auth0 application has exactly one connection enabled — a Database
(email/password) connection with **Disable Sign Ups** on — so only credentials we
create can ever reach the login form; there is no public sign-up. Roles never come
from Auth0 — they are read from the local `users` row, which must be provisioned
above before the first sign-in.

> **The password-less local dev login has been removed.** `DEV_AUTH_ENABLED` and
> `/api/auth/dev/*` no longer exist; the flag is ignored if left in a `.env`. It issued
> a real session to any provisioned email with no identity check, and once Auth0 was
> live it was pure attack surface. `tests/routes/test_auth.py` has a regression test
> asserting those paths stay gone. Recovering an environment now means provisioning
> through `scripts.provision_user`, not bypassing sign-in.

Use Chrome or Firefox — the session cookie is `Secure` + `__Host-`-prefixed even
locally, and Safari won't store it over plain HTTP.

## Auth0 application settings — two settings the code cannot check for you

Sign-in and sign-out depend on both, and get them wrong silently rather than loudly.

**1. Register `AUTH0_REDIRECT_URI` under Allowed Callback URLs**, and every
`FRONTEND_URL` you use (`http://localhost:5173` for development, plus each deployed
origin) **and that same origin + `/login`** (e.g. `http://localhost:5173/login`) under
**Allowed Logout URLs**, on the Auth0 application settings page. If a logout URL is not
registered, Auth0's `/v2/logout` **ignores** `returnTo` and leaves the user on Auth0's
own generic "you're logged out" page instead of returning them to Prompt Patrol.
Nothing errors; the user just never comes back. The `/login` entry is needed because a
rejected sign-in (deactivated/deleted/not-provisioned account) is routed through Auth0
logout with `returnTo=FRONTEND_URL/login?error=...` so Auth0's own SSO session doesn't
outlive the rejection — Auth0 ignores the query string during validation, but the path
must still be registered exactly.

**2. Disable Sign Ups on the Database connection**, and turn on tenant-wide Attack
Protection (Bot Detection, Suspicious IP Throttling, Brute-force Protection).
