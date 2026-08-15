# Prompt-Patrol

SMU CS480 Capstone Project building an web application based triage tool for university instructors to detect AI-generated short answers.

| Package                          | What it is                                                  |
| -------------------------------- | ----------------------------------------------------------- |
| [`apps/api`](apps/api/README.md) | FastAPI + SQLAlchemy + Postgres, Microsoft Entra ID sign-in |
| [`apps/web`](apps/web/README.md) | React 19 + TypeScript + Vite frontend                       |

## Local dev

1. `cd apps && docker compose up -d --build` — starts Postgres, the detector service, and the API.
2. `docker exec prompt-patrol-api alembic upgrade head` — creates the `users`/`sessions` tables (runs inside the container, so it uses the container's `DB_URL` — no host/`localhost` hostname mismatch to worry about).
3. `docker exec prompt-patrol-api sh -c "cd /app && python -m scripts.provision_user add <your-dev-tenant-email> root_admin"` — allowlist yourself; there's no self-service signup. Must be run as `-m scripts.provision_user`, not `python scripts/provision_user.py` — the latter fails with `ModuleNotFoundError: No module named 'db'` since Python puts the script's own folder on `sys.path` instead of the app root.
4. `cd apps/web && nvm use && npm install && npm run dev` — starts the frontend on <http://localhost:5173>. `nvm use` picks up `apps/web/.nvmrc`; run it from `apps/web` (or below), since nvm searches upwards and there's no `.nvmrc` at the repo root. Without a matching Node, `npm install` stops with an `EBADENGINE` error rather than failing later mid-build — see [the frontend README](apps/web/README.md#node-version).
