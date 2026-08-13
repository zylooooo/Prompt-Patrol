# Prompt-Patrol

SMU CS480 Capstone Project building an web application based triage tool for university instructors to detect AI-generated short answers.

A flag is a prompt for human review, never a verdict.

## Layout

| Path | What it holds |
| --- | --- |
| `frontend/` | React 19 + TypeScript + Vite + Tailwind client |
| `apps/api/` | FastAPI service, Alembic migrations, Docker setup |
| `apps/web/` | Minimal frontend used to wire up the auth flow end to end |
| `docs/openapi.yaml` | The API contract shared by both sides |

## Local dev

1. `cd apps && docker compose up -d --build` starts Postgres and the API.
2. `docker exec prompt-patrol-api alembic upgrade head` creates the `users` and `sessions` tables (runs inside the container, so it uses the container's `DB_URL`, no host/`localhost` hostname mismatch to worry about).
3. `docker exec prompt-patrol-api sh -c "cd /app && python -m scripts.provision_user add <your-dev-tenant-email> root_admin"` allowlists you; there is no self-service signup. Must be run as `-m scripts.provision_user`, not `python scripts/provision_user.py`, since the latter fails with `ModuleNotFoundError: No module named 'db'` because Python puts the script's own folder on `sys.path` instead of the app root.
4. Start a frontend (below).

## Frontend

```
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173.

| Command | What it does |
| --- | --- |
| `npm run dev` | Vite dev server on port 5173, proxies `/api` to localhost:8000 |
| `npm run build` | Type check, then production build |
| `npm run lint` | ESLint |

Vite is pinned to v6 on purpose: v7 and later need Node 20.19+, and the team runs
mixed Node versions. Need to agree on version.

### Signing in

There are no passwords. Sign-in goes through Microsoft Entra: the login page
sends the browser to `/api/auth/login`, Microsoft comes back through
`/api/auth/callback`, and the session lives in an HttpOnly cookie. That means
the API has to be running and your email provisioned (step 3 above) before
sign-in works. Accounts are invite-first, so there is no self-registration and
nothing to hand a new user except "sign in".

The seed roster in `src/lib/store.ts` (Dr. Don Ta, Alex Lim and friends) still
populates the Users and Teaching assistants screens, but the account you sign
in with must be provisioned on the backend.

### What is real and what is standing in

Auth is real: Entra sign-in, server-side sessions, a 30 minute idle timeout and
a 4 hour cap.

Everything else is still a stub. `src/lib/api.ts` mirrors the planned endpoints
and also enforces the permission rules, so swapping in real HTTP calls is
mechanical. Hiding a control in the UI is never the enforcement point.
`src/lib/detector.ts` is a deterministic heuristic standing in for the model,
so the same answer always scores the same and demos are repeatable.

Stub data persists in localStorage. Clearing site data resets to the seed.

## Roles

Every account has exactly one role: administrator, instructor or teaching
assistant. Roles are ranked, so an administrator passes every instructor check.
Teaching assistants relate to instructors many to many, and their access comes
from those links: a teaching assistant with no supervisor can sign in but has
nothing to screen. The backend currently records only who provisioned each
account, so shared supervision is a frontend model until that is settled.

Nothing is ever hard deleted. Deactivation is administrator only and is the
strongest action available; instructors only ever unlink.
