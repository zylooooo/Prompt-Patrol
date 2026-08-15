# Prompt-Patrol

SMU CS480 Capstone Project building an web application based triage tool for university instructors to detect AI-generated short answers.

| Package                          | What it is                                                  |
| -------------------------------- | ----------------------------------------------------------- |
| [`apps/api`](apps/api/README.md) | FastAPI + SQLAlchemy + Postgres, Microsoft Entra ID sign-in |
| [`apps/web`](apps/web/README.md) | React 19 + TypeScript + Vite frontend                       |

## Local dev

1. `cd apps && docker compose up -d --build` — starts Postgres + the API.
2. `docker exec prompt-patrol-api alembic upgrade head` — creates the `users`/`sessions` tables.
3. `docker exec prompt-patrol-api sh -c "cd /app && python -m scripts.provision_user add <your-dev-tenant-email> root_admin"` — allowlist yourself; there's no self-service signup.
4. `cd apps/web && nvm use && npm install && npm run dev` — starts the frontend on <http://localhost:5173>.

Steps 2 and 3 each fail in a non-obvious way if run slightly wrong, and sign-in
has to be configured before any of this is useful — see
[the API README](apps/api/README.md). For the frontend toolchain, Node version,
and lint setup, see [the web README](apps/web/README.md).
