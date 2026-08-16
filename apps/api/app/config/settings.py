import contextvars
import json
import logging
import logging.config
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Failure to load {name} from .env file.")
    return value


API_HOST: str = _require_env("API_HOST")
API_PORT: int = int(_require_env("API_PORT"))
DB_URL: str = _require_env("DB_URL")

FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")

DETECTOR_URL: str = os.getenv("DETECTOR_URL", "http://detector:8001")

LOG_LEVEL = os.getenv("LOG_LEVEL", "info")

VALID_ENVIRONMENTS = {"dev", "staging", "prod"}
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")
if ENVIRONMENT not in VALID_ENVIRONMENTS:
    raise ValueError(f"Invalid ENVIRONMENT '{ENVIRONMENT}', expected one of {VALID_ENVIRONMENTS}.")


_ENTRA_VARS = ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET", "ENTRA_REDIRECT_URI")
_entra_missing = sorted(name for name in _ENTRA_VARS if not (os.getenv(name) or "").strip())

if _entra_missing:
    raise ValueError(
        f"Incomplete Entra configuration - {', '.join(_entra_missing)} missing. "
        "All of ENTRA_TENANT_ID/ENTRA_CLIENT_ID/ENTRA_CLIENT_SECRET/"
        "ENTRA_REDIRECT_URI must be set. Refusing to start an app nobody can "
        "sign into."
    )

ENTRA_TENANT_ID: str = _require_env("ENTRA_TENANT_ID").strip()
ENTRA_CLIENT_ID: str = _require_env("ENTRA_CLIENT_ID").strip()
ENTRA_CLIENT_SECRET: str = _require_env("ENTRA_CLIENT_SECRET").strip()
ENTRA_REDIRECT_URI: str = _require_env("ENTRA_REDIRECT_URI").strip()
SESSION_SECRET: str = _require_env("SESSION_SECRET")

# Hosts a browser will accept a Secure cookie from over plain http.
_TRUSTWORTHY_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


# Refuses to start when the URLs cannot hold a __Host- session cookie.
def validate_session_cookie_hosts(frontend_url: str, redirect_uri: str) -> None:
    frontend, redirect = urlparse(frontend_url), urlparse(redirect_uri)

    if not frontend.hostname or not redirect.hostname:
        raise ValueError(
            "FRONTEND_URL and ENTRA_REDIRECT_URI must be absolute URLs with a scheme and host - "
            f"got FRONTEND_URL={frontend_url!r}, ENTRA_REDIRECT_URI={redirect_uri!r}."
        )

    if frontend.hostname != redirect.hostname:
        raise ValueError(
            f"FRONTEND_URL host '{frontend.hostname}' and ENTRA_REDIRECT_URI host "
            f"'{redirect.hostname}' differ. The session cookie is '__Host-session', and the "
            "__Host- prefix forbids a Domain attribute, so the cookie is pinned to whichever "
            "host answers the Entra callback. Split across two hosts, sign-in appears to "
            "succeed and then every request is 401 with nothing logged anywhere. Serve both "
            "from one host - see apps/web/nginx.conf. Ports may differ; cookies ignore them."
        )

    insecure = [
        name
        for name, parsed in (("FRONTEND_URL", frontend), ("ENTRA_REDIRECT_URI", redirect))
        if parsed.scheme != "https"
    ]
    if insecure and frontend.hostname not in _TRUSTWORTHY_LOCAL_HOSTS:
        raise ValueError(
            f"{' and '.join(insecure)} must use https on host '{frontend.hostname}'. The session "
            "cookie is set Secure with a __Host- prefix, which browsers accept over plain http "
            "only for localhost, so here it is dropped silently and nobody can sign in."
        )


validate_session_cookie_hosts(FRONTEND_URL, ENTRA_REDIRECT_URI)

request_id_ctx_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": _RequestIdFilter}},
            "formatters": {
                "plain": {
                    "format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s",
                },
                "json": {"()": _JsonFormatter},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json" if ENVIRONMENT == "prod" else "plain",
                    "filters": ["request_id"],
                },
            },
            "root": {"handlers": ["default"], "level": LOG_LEVEL.upper()},
        }
    )
