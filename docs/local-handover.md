# Running Prompt Patrol locally

The whole application on one machine with Docker Compose: the detector (desklib + MELD), the API, the batch worker,
the web app and the database. No cloud account is needed. **Sign-in uses Auth0, so the machine must be online.**

## Running it

Install and run instructions for end users live in [`release/README.md`](../release/README.md), shipped in the
release zip next to an image-only `compose.yml`. Images are built and published by `.github/workflows/release.yml`.
For development, `apps/docker-compose.yml` builds from source and reads `apps/api/.env`.

The notes below are for the team and for whoever takes over the Auth0 tenant and the domain.

## How it is laid out

The networks copy the AWS design. Only the web app (port 5173) and the S3 stand-in (port 4566, for batch CSV
uploads from the browser) can be reached from the machine, and only from `localhost`. The database, detector and
worker have no ports and no internet access. Only the API can reach the internet, for Auth0. Check history is
hard-deleted after 90 days by the `purge` service, as in AWS.

![Prompt Patrol local architecture, orchestrated by Docker Compose](assets/prompt-patrol-local-architecture.png)

The diagram source is [`assets/prompt-patrol-local-architecture.drawio`](assets/prompt-patrol-local-architecture.drawio).
Re-export the PNG from draw.io when `release/compose.yml` changes.

Differences from AWS: no HTTPS and no WAF (the browser treats `localhost` as secure), and access rules are per
network rather than per port. Uploaded batch CSVs are not expired after 60 days as they are in AWS.

## Auth0 settings (for the team)

The hand-over uses the one and only production Auth0 tenant set up by the development team.

> ***Note: ONLY applicable if there are going to be multiple instances of Prompt Patrol running***
>
> **Use one Auth0 tenant per install.** The app assumes one tenant maps to one database. Seeding the same root admin on
> several machines is fine (the seed reuses the existing credential). But adding a user on one machine deletes any
> Auth0 credential that has no local account on that machine, and deleting a user removes the shared credential, so
> the other machines' accounts stop working ("not set up yet"). If several people run their own copy, give each its
> own tenant, or have them share one database.

Tenant setup checklist:

- Regular Web Application. Allowed Callback URLs `http://localhost:5173/api/auth/callback`. Allowed Logout URLs
  `http://localhost:5173` and `http://localhost:5173/login`.
- Only the Database connection (`Username-Password-Authentication`, the name the API expects) enabled, with Disable
  Sign Ups on. **Delete the default `google-oauth2` social connection** on a new tenant. It uses Auth0's dev keys
  (the warning on the sign-in page) and bypasses Disable Sign Ups.
- Attack Protection on (brute-force protection at least).
- An M2M application authorized for the Management API with `create:users`, `read:users` and `delete:users`. Do not
  widen it.
- The Post Login Action that clears `pending_activation`.
- The three email templates from `docs/assets/`. The Change Password one already links to
  `http://localhost:5173/login`.
- Tenant Settings: friendly name "Prompt Patrol", the logo URL, error page left on Generic.
- Universal Login: the theme, and the custom text (English) for login-id, login-password, the five reset-password
  screens and logout. The reset-password-success description reads "Your password has been changed. Head back to
  Prompt Patrol at `http://localhost:5173` to sign in." The `logout-aborted` screen can't be edited on a new tenant;
  leave it on Auth0's default.
- Rotate both client secrets after the hand-over.

Running locally limits what Auth0 can link back to. Auth0 only accepts https, non-localhost addresses for the
Application Login URI and the custom error page, and "Redirect To" is enterprise-only. So the Login URI is left
empty on purpose, and the way back to the app is:

- the clickable `http://localhost:5173/login` link in the invite and reset emails, and
- a plain-text line on the reset-success page (HTML in custom text is shown as text, so it is not clickable).

Errors during sign-in show Auth0's generic error page.

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
- **Sign-in link.** The Application Login URI is empty (see above), so nothing depends on the domain for the link
  back to the app.

To keep everything working, either:

1. take over `prompt-patrol.com`, the Resend account and the logo hosting from the team, or
2. use your own domain. Add it to Resend (or another email provider in Auth0), change the sender address in Auth0's
   email provider and in all three email templates, host `wordmark.png` and `wordmark-email.png` somewhere public
   over HTTPS, and update the logo URL in Auth0 Tenant Settings, the Universal Login theme and the email templates.
