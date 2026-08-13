
import os
import json
import logging
import secrets
import contextvars
import logging.config
from pathlib import Path
from dotenv import load_dotenv

# Get the API base directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load the .env variables
load_dotenv(BASE_DIR / '.env')

def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Failure to load {name} from .env file.")
    return value

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"", "0", "false", "no", "off"}


def _parse_bool(name: str, raw: str | None) -> bool:
    normalized = (raw or "").strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    raise ValueError(
        f"{name} must be one of {sorted(_TRUTHY | _FALSY - {''})} (or unset), got {raw!r}."
    )

API_HOST: str = _require_env("API_HOST")
API_PORT: int = int(_require_env("API_PORT"))
DB_URL: str = _require_env("DB_URL")

FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")

LOG_LEVEL = os.getenv("LOG_LEVEL", 'info')

VALID_ENVIRONMENTS = {"dev", "staging", "prod"}
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")
if ENVIRONMENT not in VALID_ENVIRONMENTS:
    raise ValueError(
        f"Invalid ENVIRONMENT '{ENVIRONMENT}', expected one of {VALID_ENVIRONMENTS}."
    )

def resolve_dev_auth_enabled(raw: str | None, environment: str) -> bool:
    enabled = _parse_bool("DEV_AUTH_ENABLED", raw)
    if enabled and environment != "dev":
        raise ValueError(
            f"DEV_AUTH_ENABLED is set but ENVIRONMENT is '{environment}'. The "
            "password-less local login is only ever allowed under "
            "ENVIRONMENT=dev. Remove DEV_AUTH_ENABLED to start the app."
        )
    return enabled

DEV_AUTH_ENABLED: bool = resolve_dev_auth_enabled(os.getenv("DEV_AUTH_ENABLED"), ENVIRONMENT)

_ENTRA_VARS = ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET", "ENTRA_REDIRECT_URI")
_entra_values = {name: (os.getenv(name) or "").strip() for name in _ENTRA_VARS}
_entra_missing = sorted(name for name, value in _entra_values.items() if not value)

if _entra_missing and len(_entra_missing) != len(_ENTRA_VARS):
    raise ValueError(
        f"Partial Entra configuration - {', '.join(_entra_missing)} missing. "
        "Set all of ENTRA_TENANT_ID/ENTRA_CLIENT_ID/ENTRA_CLIENT_SECRET/"
        "ENTRA_REDIRECT_URI, or leave all of them blank and use DEV_AUTH_ENABLED."
    )

ENTRA_CONFIGURED: bool = not _entra_missing
ENTRA_TENANT_ID: str | None = _entra_values["ENTRA_TENANT_ID"] or None
ENTRA_CLIENT_ID: str | None = _entra_values["ENTRA_CLIENT_ID"] or None
ENTRA_CLIENT_SECRET: str | None = _entra_values["ENTRA_CLIENT_SECRET"] or None
ENTRA_REDIRECT_URI: str | None = _entra_values["ENTRA_REDIRECT_URI"] or None

if not ENTRA_CONFIGURED and not DEV_AUTH_ENABLED:
    raise ValueError(
        "No login method is configured. Either fill in the four ENTRA_* "
        "variables, or set DEV_AUTH_ENABLED=true for the local-only dev login "
        "(requires ENVIRONMENT=dev). Refusing to start an app nobody can sign "
        "into."
    )

_session_secret = os.getenv("SESSION_SECRET")
if ENTRA_CONFIGURED and not _session_secret:
    raise ValueError("Failure to load SESSION_SECRET from .env file.")
SESSION_SECRET: str = _session_secret or secrets.token_urlsafe(48)

request_id_ctx_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

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
