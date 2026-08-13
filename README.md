# Prompt-Patrol

SMU CS480 Capstone Project building an web application based triage tool for university instructors to detect AI-generated short answers.

## Local dev

1. `cd apps && docker compose up -d --build` — starts Postgres + the API.
2. `docker exec prompt-patrol-api alembic upgrade head` — creates the `users`/`sessions` tables (runs inside the container, so it uses the container's `DB_URL` — no host/`localhost` hostname mismatch to worry about).
3. `docker exec prompt-patrol-api sh -c "cd /app && python -m scripts.provision_user add <your-dev-tenant-email> root_admin"` — allowlist yourself; there's no self-service signup. Must be run as `-m scripts.provision_user`, not `python scripts/provision_user.py` — the latter fails with `ModuleNotFoundError: No module named 'db'` since Python puts the script's own folder on `sys.path` instead of the app root.
4. `cd apps/web && npm install && npm run dev` — starts the frontend on <http://localhost:5173>.

### Signing in

Two paths. Pick one in `apps/api/.env`; the API refuses to start with neither.

**Microsoft Entra ID** — fill in `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `ENTRA_REDIRECT_URI` and `SESSION_SECRET`. All four `ENTRA_*` are required together; a partial fill is a startup error rather than a half-working OAuth client.

**Local dev login** — for working without an Entra app registration. Leave all four `ENTRA_*` blank and set `DEV_AUTH_ENABLED=true`. The login page then offers a picker of provisioned accounts and signs you in as one, no Microsoft round trip.

This skips *authentication* only. It does not skip *authorization*: step 3 above is still required, the account must still exist and not be soft-deleted, and the role still comes from the `users` row — nothing in the request can create a user or pick a role. Sessions it issues are ordinary sessions with the same cookie hardening and TTLs.

It is confined to a developer's machine by four independent gates:

- `DEV_AUTH_ENABLED` is refused unless `ENVIRONMENT=dev` — the app raises at startup rather than quietly ignoring the flag, so a stray value in a real environment stops a deploy instead of going unnoticed.
- `/api/auth/dev/*` is only mounted when the flag is set; in staging/prod those paths don't exist, and `routes/dev_auth.py` is never even imported.
- The router re-checks the flag per request, so mounting it by mistake still yields 404s.
- The login page's dev panel is behind `import.meta.env.DEV`, so `npm run build` strips it from the production bundle entirely.

`docker-compose.yml` also publishes the API on `127.0.0.1:8000` rather than every interface, so the dev login isn't reachable from your LAN. Use Chrome or Firefox — the session cookie is `Secure` + `__Host-`-prefixed even locally, and Safari won't store it over plain HTTP.
