# Prompt-Patrol

[![CI](https://github.com/zylooooo/Prompt-Patrol/actions/workflows/ci.yml/badge.svg)](https://github.com/zylooooo/Prompt-Patrol/actions/workflows/ci.yml)

SMU CS480 Capstone Project building an web application based triage tool for university instructors to detect AI-generated short answers.

| Package                                              | What it is                                                                                     |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| [`apps/api`](apps/api/README.md)                     | FastAPI + SQLAlchemy + Postgres, Auth0 sign-in                                                 |
| [`apps/web`](apps/web/README.md)                     | React 19 + TypeScript + Vite frontend                                                          |
| [`apps/data-pipeline`](apps/data-pipeline/README.md) | Corpus tooling: dataset ingest and cleaning, the AI-answer generation harness, and the splicer |

## Local dev

1. `cd apps && docker compose up -d --build` — starts Postgres, the detector service, the API, and an nginx-served production build of the frontend on <http://localhost:5173>. The API reads `apps/api/.env`, and `apps/api/app/config/settings.py` refuses to start unless all six `AUTH0_*` variables are set — an incomplete Auth0 configuration is a startup failure rather than a runtime one, on the grounds that an app nobody can sign into should say so immediately. The API also applies migrations on start (`apps/api/entrypoint.sh`), so the tables are there by the time it answers its health check. A failed migration stops the container rather than leaving it serving errors, so `docker compose logs api` is the first place to look if it does not come up.
2. `docker exec prompt-patrol-api sh -c "cd /app && python -m scripts.provision_user add <your-dev-tenant-email> root_admin"` — allowlist yourself; there's no self-service signup. This also creates your Auth0 credential — Auth0 emails you a one-time link to set your password before signing in. Must be run as `-m scripts.provision_user`, not `python scripts/provision_user.py` — the latter fails with `ModuleNotFoundError: No module named 'db'` since Python puts the script's own folder on `sys.path` instead of the app root.
3. `cd apps/web && nvm use && npm install && npm run dev` — starts the Vite dev server, which proxies `/api` to the API on port 8000. `.nvmrc` lives at the **repo root**, not in `apps/web`; nvm searches upwards, so `nvm use` resolves to it from anywhere in the tree and one file covers every working directory — see [the frontend README](apps/web/README.md#node-version). Without a matching Node, `npm install` stops with an `EBADENGINE` error rather than failing later mid-build.

   Step 1 has already put the containerised frontend on 5173, so stop it first (`docker compose stop frontend`). Otherwise Vite falls back to the next free port and you spend the afternoon testing the image you built rather than the edits you just made.

To apply a migration you have just written without restarting anything, `docker exec prompt-patrol-api alembic upgrade head` still works — it runs inside the container, so it uses the container's `DB_URL` and there is no host/`localhost` hostname mismatch to worry about.

## End-to-end tests

`cd apps/web && npm run test:e2e` — runs the Playwright smoke suite against its own throwaway stack (`apps/e2e/docker-compose.yml`), built, seeded and torn down by that one command. Stop the dev stack first, since both bind the same ports. Auth0 and the detector are stubbed — see [the frontend README](apps/web/README.md#end-to-end-tests) for what that covers and why.
