# Prompt Patrol: run it on your own machine

Prompt Patrol is an instructor-facing tool that flags potentially AI-generated short student answers for human review.
This guide walks you through running the whole application on your own machine from prebuilt Docker images,
orchestrated with Docker Compose. All released images are stored in our personal
[GitHub Container Registry (GHCR)](<https://github.com/zylooooo?tab=packages&repo_name=Prompt-Patrol>). Running the
[`compose.yml`](compose.yml) will pull the latest released images from GHCR. Finally, the app will be orchestrated with
`Docker Compose`.

> **NOTE**: Sign-in (Auth0) and email (Resend) are online services, so the machine must be connected to the internet.
>
> **Run only one copy of Prompt Patrol per Auth0 tenant.** Each copy has its own database, but they would share the
> tenant's accounts: adding or deleting a user on one copy removes the sign-in for that email on every other copy
> ("not set up yet"). If more than one copy is needed, each one needs its own Auth0 tenant. Ask the team.

## What you need

|           | Minimum                                                      | Comfortable |
| --------- | ------------------------------------------------------------ | ----------- |
| RAM       | 16 GB, with Docker given 12 GB                               | 32 GB       |
| Free disk | 20 GB                                                        | 30 GB       |
| CPU       | 4 cores, x86_64 or Apple Silicon                             | 8 cores     |
| Network   | Online: sign-in (Auth0) and the first image download (~6 GB) |             |

You also need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with the Compose
plugin) and Chrome or Firefox. No GPU is needed.

### Give Docker 12 GB of memory

The detector uses about 6–7.5 GB and is **killed while loading if Docker has less than about 12 GB**. Docker Desktop
defaults to half your RAM, which on a 16 GB machine is too little.

- Mac, or Windows with Hyper-V: Docker Desktop → Settings → Resources → Memory limit.
- Windows with WSL 2: put this in `%UserProfile%\.wslconfig`, then run `wsl --shutdown` and restart Docker Desktop:

  ```ini
  [wsl2]
  memory=12GB
  ```

**Less than 16 GB of RAM?** It may still work, but expect trouble. Give Docker as much as you can while leaving Windows
or macOS about 3 GB, add swap to ride out the load peak (`swap=8GB` under `[wsl2]`; on Docker Desktop, Settings →
Resources → Swap), and close other heavy programs until `docker compose ps` shows the detector healthy. If the detector
keeps restarting or shows `Exited (137)`, Docker is still short of memory: use a machine with 16 GB or more.

## 1. Get the package

Download the latest `prompt-patrol-<version>.zip` from the [Release page](https://github.com/zylooooo/Prompt-Patrol/releases)
and unzip it. Open a terminal in the unzipped folder. It should contain the following files:

1. [`compose.yml`](compose.yml)
2. [`.env.example`](./.env.example)
3. [`localstack-init.sh`](localstack-init.sh)
4. `README.md` *(this file)*

## 2. Configure

```sh
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env
```

Fill in every blank value in `.env`:

- **Auth0 values** (`AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_M2M_CLIENT_ID`,
  `AUTH0_M2M_CLIENT_SECRET`): they are never inside this package. Either copy them yourself from the Auth0 dashboard
  (Applications → the login app and the M2M app → Settings) once the team gives you admin access to the tenant, or
  the team sends them to you over a secure channel. Rotate both client secrets once you have them, so only you hold
  working copies.
- **Database**: pick any `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, then build `DB_URL` from them:
  `postgresql+asyncpg://<user>:<password>@postgres:5432/<db>`. Use letters and digits in the password.
- **`SESSION_SECRET`**: at least 32 random characters, for example
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

Leave everything else as it is. If a required value is blank, the API stops at start and `docker compose logs api`
names it. (A blank `POSTGRES_*` value shows up in `docker compose logs postgres` instead.)

> If you are unsure what to put in `.env`, ask the development team.

## 3. Start

```sh
docker compose up -d
docker compose ps           # wait until api shows "healthy"
```

The first start downloads about 6 GB. The detector then takes 2–5 minutes to load models on every start. You can sign
in while it loads; checks fail until `docker compose ps` shows the detector as healthy.

Open <http://localhost:5173> in **Chrome or Firefox**. Safari won't keep the sign-in cookie over plain `http`, so
signing in appears to do nothing.

## 4. Create the first administrator

There is no sign-up page. Create the first account from the command line. Auth0 then emails that address a one-time
link to set the password:

```sh
docker compose exec api sh -c "cd /app && python -m scripts.provision_user add <your-email> root_admin"
```

Running it again is safe: if the account already exists it does nothing and sends no email. After
`docker compose down -v` it reuses the credential Auth0 already has for that address instead of sending a new invite.

After that, add instructors and TAs from the Users page.

## Stop, restart, reset

```sh
docker compose stop            # stop, keep data
docker compose up -d           # start again
docker compose down -v         # delete everything, including the database
docker compose logs api        # first place to look if something doesn't start
```

Uploaded batch CSVs and queued batch work are held in memory by LocalStack (the S3/SQS stand-in), not on disk, so
restarting it, the stack or the machine clears them. **Let running batches finish before you stop the stack.** Users
and check history live in the database volume and survive restarts until `docker compose down -v`. Check history is
deleted automatically after 90 days.

`.env` holds your passwords and Auth0 secrets. Don't share it, and don't paste the output of `docker compose config`
or `docker inspect` anywhere: both print those values.

## Back up and restore the database

`docker compose down -v` deletes every user and all check history, with no undo. Take a backup first:

```sh
docker compose exec postgres sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" -f /tmp/backup.dump'
docker compose cp postgres:/tmp/backup.dump ./backup.dump
```

To restore into a running stack:

```sh
docker compose stop api worker purge frontend
docker compose cp ./backup.dump postgres:/tmp/backup.dump
docker compose exec postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/backup.dump'
docker compose up -d
```

The backup contains student data. Keep it somewhere private and delete it when you no longer need it.

## Upgrade

Download the new zip, replace every file except your `.env`, then:

```sh
docker compose pull
docker compose up -d
```

Images are pinned to the version in `compose.yml` and never change underneath you. To run a specific version, set
`PP_VERSION` in `.env`.

## Troubleshooting

- **The worker keeps restarting and `docker compose logs localstack` says "No such file or directory".**
  `localstack-init.sh` has Windows (CRLF) line endings, usually from re-saving it in an editor. It must use LF. Unzip a
  fresh copy and don't edit it.
- **`docker compose up` says `denied` when pulling.** The images should be public. Tell the team.
- **Checks fail with a "detector" error right after start.** It is still loading models. Wait until
  `docker compose ps` shows `detector` healthy (2–5 minutes).
- **The detector restarts in a loop, or shows `Exited (137)`.** Docker has too little memory. See
  [Give Docker 12 GB of memory](#give-docker-12-gb-of-memory).
- **The API exits at start.** `docker compose logs api` names the `.env` value that is missing or too short.
- **Port 5173 or 4566 is already in use.** Stop whatever uses it; both ports are fixed.

## How it is laid out

Only the web app (port 5173) and the S3 stand-in (port 4566, for batch CSV uploads from the browser) can be reached
from the machine, and only from `localhost`. The database, detector and worker have no ports and no internet access.
Only the API can reach the internet, for Auth0. The architecture design is intentional and we want to follow our
intended production environment on cloud as closely as possible.

See the [local architecture diagram](https://github.com/zylooooo/Prompt-Patrol/blob/main/docs/assets/prompt-patrol-local-architecture.png)
for how the containers, networks and the two published ports fit together. It is a link rather than an embedded image
because the docs folder is not part of this package.
