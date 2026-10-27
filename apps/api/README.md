# Prompt Patrol — API

FastAPI + SQLAlchemy + Postgres, with Auth0 sign-in. See the
[repo README](../../README.md) for running the full stack; this file covers the
backend only. The endpoints themselves are specified in
[`docs/openapi.yaml`](../../docs/openapi.yaml).

## Layout

| Path                | What lives there                                                                 |
| ------------------- | -------------------------------------------------------------------------------- |
| `app/main.py`       | Entry point: middleware and router wiring                                        |
| `app/routes/`       | One router per module: `auth`, `checks`, `batches`, `users`                      |
| `app/services/`     | Domain logic. Routes stay thin; the worker calls `create_check` from here too    |
| `app/models/`       | SQLAlchemy models                                                                |
| `app/schemas/`      | Pydantic request/response models, mirroring the contract                         |
| `app/auth/`         | OIDC flow, session handling, the Auth0 Management API client, `Depends()` guards |
| `app/exceptions/`   | Domain exceptions and the handlers that map them to HTTP responses               |
| `app/config/`       | `settings.py` — reads and validates the environment at import time               |
| `app/scripts/`      | `provision_user` and `e2e_seed`, run with `python -m` inside the container       |
| `alembic/versions/` | Migrations                                                                       |

There is no `app/__init__.py`, by design: `app/` is the import root (the
Dockerfile copies it to `/app`). Import across packages through the package's
`__init__.py` (`from services import create_check`), not its submodules.

## Configuration

`apps/api/.env`, copied from `.env.example`. `settings.py` validates it at
import time, so a bad configuration stops the container on start rather than
failing on the first request.

| Variables                                                                                         | Notes                                                                                |
| ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `API_HOST`, `API_PORT`, `DB_URL`                                                                  | Required                                                                             |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`                                               | Read by the Postgres container, which shares this file                               |
| `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_REDIRECT_URI`                    | Required. The authentication provider                                                |
| `AUTH0_M2M_CLIENT_ID`, `AUTH0_M2M_CLIENT_SECRET`                                                  | Required. A separate M2M application for the Management API, used to provision       |
| `SESSION_SECRET`                                                                                  | Required. Signs the OAuth state cookie                                               |
| `FRONTEND_URL`                                                                                    | Defaults to `http://localhost:5173`                                                  |
| `ENVIRONMENT`                                                                                     | `dev` (default), `staging` or `prod`                                                 |
| `DETECTOR_URL`                                                                                    | Defaults to `http://detector:8001`                                                   |
| `AWS_REGION`, `AWS_ENDPOINT_URL`, `AWS_ENDPOINT_URL_PUBLIC`, `S3_BATCHES_BUCKET`, `SQS_*`         | Batch uploads. Endpoint URLs name LocalStack locally; leave unset in AWS             |
| `DETECTOR_MODEL_VERSION`, `DETECTOR_CALIBRATION_VERSION`, `DETECTOR_THRESHOLD`, `ABSTENTION_BAND` | Leave unset for the default RoBERTa detector; `docker-compose.desklib.yml` sets them |

Outside `dev`, two more checks refuse to start the app, because both failures
are otherwise silent — sign-in appears to work and then every request is `401`:

- `SESSION_SECRET` must be at least 32 characters and not a known placeholder.
- `FRONTEND_URL` and `AUTH0_REDIRECT_URI` must share a host (the `__Host-`
  session cookie cannot span two), and use `https` anywhere but localhost.

The four detector variables describe whichever model the detector is serving,
so they change together with the detector image rather than per developer.
Unset, they match the default RoBERTa baseline; `apps/docker-compose.desklib.yml`
sets them when it swaps in the desklib detector. Keep them commented out in
`.env` — the desklib threshold applied to the baseline model would flag almost
nothing, without an error.

## Migrations

`entrypoint.sh` runs `alembic upgrade head` on every container start, and a
failed migration stops the container. To apply one you have just written
without restarting:

```bash
docker exec prompt-patrol-api alembic upgrade head
```

Run it inside the container so it uses the container's `DB_URL` — that way
there's no host/`localhost` hostname mismatch to work around.

## Provisioning accounts

There is no self-service signup, so every account has to be allowlisted before
its first sign-in. This also creates their Auth0 credential through the
Management API, and Auth0 emails them a one-time link to set their own
password. The Auth0 call happens before the local row is committed, so a
failure there leaves nothing behind.

```bash
docker exec prompt-patrol-api sh -c "cd /app && python -m scripts.provision_user add <your-dev-tenant-email> root_admin"
```

Must be run as `-m scripts.provision_user`, not
`python scripts/provision_user.py` — the latter fails with
`ModuleNotFoundError: No module named 'db'`, since Python puts the script's own
folder on `sys.path` instead of the app root.

## Signing in

**Auth0 is the only way in**, in every environment including local development.
There is no password-less dev login; recovering an environment means
provisioning through `scripts.provision_user`, not bypassing sign-in.

The flow is Authorization Code + PKCE (`S256`) against Auth0's discovery document.
The Auth0 application has exactly one connection enabled — a Database
(email/password) connection with **Disable Sign Ups** on — so only credentials we
create can ever reach the login form; there is no public sign-up. Roles never come
from Auth0 — they are read from the local `users` row, which must be provisioned
above before the first sign-in.

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

## Tests

```bash
pip install -r requirements.txt
pytest
```

`settings.py` still loads `apps/api/.env`, so fill it in first. Tests use an
in-memory SQLite database by default; set `TEST_DB_URL` to a Postgres URL to
run them against Postgres, as CI does. Postgres catches things SQLite does not,
so if a test passes locally and fails in CI, rerun it against Postgres before
looking anywhere else. `ruff check .` is the linter CI runs.
