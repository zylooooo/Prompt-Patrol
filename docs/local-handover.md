# Running Prompt Patrol locally

The whole application on one machine with Docker Compose: the detector (desklib + MELD), the API, the batch worker,
the web app and the database. No cloud account is needed. **Sign-in uses Auth0, so the machine must be online.**

## What you need

|           | Minimum                                                      | Comfortable |
| --------- | ------------------------------------------------------------ | ----------- |
| RAM       | 16 GB, with Docker given 12 GB                               | 32 GB       |
| Free disk | 20 GB                                                        | 30 GB       |
| CPU       | 4 cores, x86_64 or Apple Silicon                             | 8 cores     |
| Network   | Online: sign-in (Auth0) and the first image download (~6 GB) |             |

No GPU is needed. The detector uses about 6–7.5 GB of memory and takes 2–5 minutes to load on each start. You can
sign in while it loads; checks fail until `docker compose ps` shows the detector as healthy.

**Give Docker 12 GB of memory.** Docker Desktop defaults to half your RAM, which on a 16 GB machine is too little,
and the detector is killed while loading.

- Mac, or Windows with Hyper-V: Docker Desktop → Settings → Resources → Memory limit.
- Windows with WSL 2: put this in `%UserProfile%\.wslconfig`, then run `wsl --shutdown` and restart Docker Desktop:

  ```ini
  [wsl2]
  memory=12GB
  ```

## 1. Configure

```sh
cd apps
cp api/.env.example api/.env
```

Fill in `api/.env`. The team sends the `AUTH0_*` values separately, never inside this package.

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and `DB_URL` built from them:
  `postgresql+asyncpg://<user>:<password>@postgres:5432/<db>`
- `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_M2M_CLIENT_ID`, `AUTH0_M2M_CLIENT_SECRET`
- `AUTH0_REDIRECT_URI=http://localhost:5173/api/auth/callback` and `FRONTEND_URL=http://localhost:5173`
- `ENVIRONMENT=prod`, as in production: redacted JSON logs and no auto-reload. (The team develops with `dev`.)
- `SESSION_SECRET`: at least 32 random characters, for example `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- AWS settings for the local S3/SQS stand-in:

  ```ini
  AWS_REGION=us-east-1
  AWS_ENDPOINT_URL=http://localstack:4566
  AWS_ENDPOINT_URL_PUBLIC=http://localhost:4566
  S3_BATCHES_BUCKET=prompt-patrol-batches
  SQS_BATCHES_QUEUE_URL=http://localstack:4566/000000000000/prompt-patrol-batches
  SQS_BATCHES_DLQ_URL=http://localstack:4566/000000000000/prompt-patrol-batches-dlq
  ```

## 2. Start

```sh
docker compose up -d --build
docker compose ps          # wait until api shows "healthy"
```

Open <http://localhost:5173> in **Chrome or Firefox**. Safari won't keep the sign-in cookie over plain `http`, so
signing in appears to do nothing.

## 3. Create the first administrator

There is no sign-up page. Create the first account from the command line. Auth0 then emails that address a one-time
link to set the password:

```sh
docker compose exec api sh -c "cd /app && python -m scripts.provision_user add <your-email> root_admin"
```

After that, add instructors and TAs from the Users page.

## Stop, restart, reset

```sh
docker compose stop            # stop, keep data
docker compose up -d           # start again
docker compose down -v         # delete everything, including the database
docker compose logs api        # first place to look if something doesn't start
```

## How it is laid out

The networks copy the AWS design. Only the web app (port 5173) and the S3 stand-in (port 4566, for batch CSV
uploads from the browser) can be reached from the machine, and only from `localhost`. The database, detector and
worker have no ports and no internet access. Only the API can reach the internet, for Auth0. Check history is
hard-deleted after 90 days by the `purge` service, as in AWS.

Differences from AWS: no HTTPS and no WAF (the browser treats `localhost` as secure), and access rules are per
network rather than per port. Uploaded batch CSVs are not expired after 60 days as they are in AWS: they stay until
`docker compose down -v`, so remove the stack when you are done with real student data.

## Auth0 settings (for the team)

The hand-over uses its own production Auth0 Client

- Regular Web Application. Allowed Callback URLs `http://localhost:5173/api/auth/callback`. Allowed Logout URLs
  `http://localhost:5173` and `http://localhost:5173/login`.
- Only the Database connection enabled, with Disable Sign Ups on.
- An M2M application authorized for the Management API with `create:users`, `read:users` and `delete:users`.
- Rotate both client secrets after the hand-over.
- This tenant is separate from the team's dev and production tenant, so provisioning here does not lock anyone out
  there.

*Some of the features in Auth0 might not work. E.g., the hyperlink to link back to the login page is only applicable for `https` links. Since we are running locally, the redirection will not work after password resets, new account set up etc.*

## The `prompt-patrol.com` domain

Auth0 still depends on the team's domain `prompt-patrol.com` even when the app runs locally. The domain, its DNS
(Route 53) and the logo files all live in the team's AWS account, and the Resend account belongs to the team. If the
domain lapses, or the team's AWS account or Resend account is closed, these stop working:

- **Email.** Auth0 sends invite, password-reset and account-alert emails through Resend as
  `no-reply@mail.prompt-patrol.com`. Resend only sends from a domain whose DNS records it can verify. Without the
  domain, no emails go out. New users get no activation link and can't sign in for the first time, and nobody can
  reset a password.
- **Logos.** The sign-in page logo and the email logo are loaded from `https://app.prompt-patrol.com/brand/`. That
  address is the team's S3 bucket behind CloudFront. Without the domain the images break. Keeping them costs a small
  monthly amount: S3 storage and CloudFront requests, plus about USD 0.50/month for the Route 53 hosted zone and a
  yearly domain renewal (auto-renew is off; the domain expires on 2027-10-20).
- **"Back to Prompt Patrol" link.** The Auth0 Application Login URI points at `https://app.prompt-patrol.com/login`.

To keep everything working, either:

1. take over `prompt-patrol.com`, the Resend account and the logo hosting from the team, or
2. use your own domain. Add it to Resend (or another email provider in Auth0), change the sender address in Auth0's
   email provider and in all three email templates, host `wordmark.png` and `wordmark-email.png` somewhere public
   over HTTPS, and update the logo URL in Auth0 Tenant Settings, the Universal Login theme and the email templates.
