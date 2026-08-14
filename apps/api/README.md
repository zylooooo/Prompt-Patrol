# Prompt Patrol — API

FastAPI + SQLAlchemy + Postgres, with Microsoft Entra ID sign-in. See the
[repo README](../../README.md) for running the full stack; this file covers the
backend only.

## Migrations

```
docker exec prompt-patrol-api alembic upgrade head
```

Creates the `users`/`sessions` tables. Run it inside the container so it uses the
container's `DB_URL` — that way there's no host/`localhost` hostname mismatch to
work around.

## Provisioning accounts

There is no self-service signup, so every account has to be allowlisted before
its first sign-in.

```
docker exec prompt-patrol-api sh -c "cd /app && python -m scripts.provision_user add <your-dev-tenant-email> root_admin"
```

Must be run as `-m scripts.provision_user`, not
`python scripts/provision_user.py` — the latter fails with
`ModuleNotFoundError: No module named 'db'`, since Python puts the script's own
folder on `sys.path` instead of the app root.

## Signing in

Two paths. Pick one in `.env`; the API refuses to start with neither.

**Microsoft Entra ID** — fill in `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `ENTRA_REDIRECT_URI` and `SESSION_SECRET`. All four `ENTRA_*` are required together; a partial fill is a startup error rather than a half-working OAuth client.

**Local dev login** — for working without an Entra app registration. Leave all four `ENTRA_*` blank and set `DEV_AUTH_ENABLED=true`. The login page then offers a picker of provisioned accounts and signs you in as one, no Microsoft round trip.

This skips _authentication_ only. It does not skip _authorization_: the account must still have been provisioned above, must still exist and not be soft-deleted, and the role still comes from the `users` row — nothing in the request can create a user or pick a role. Sessions it issues are ordinary sessions with the same cookie hardening and TTLs.

It is confined to a developer's machine by four independent gates:

- `DEV_AUTH_ENABLED` is refused unless `ENVIRONMENT=dev` — the app raises at startup rather than quietly ignoring the flag, so a stray value in a real environment stops a deploy instead of going unnoticed.
- `/api/auth/dev/*` is only mounted when the flag is set; in staging/prod those paths don't exist, and `routes/dev_auth.py` is never even imported.
- The router re-checks the flag per request, so mounting it by mistake still yields 404s.
- The login page's dev panel is behind `import.meta.env.DEV`, so `npm run build` strips it from the production bundle entirely.

`docker-compose.yml` also publishes the API on `127.0.0.1:8000` rather than every interface, so the dev login isn't reachable from your LAN. Use Chrome or Firefox — the session cookie is `Secure` + `__Host-`-prefixed even locally, and Safari won't store it over plain HTTP.
