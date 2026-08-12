import contextvars
import json
import logging
import logging.config
import os
from pathlib import Path
from dotenv import load_dotenv

# Get the API base directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load env varaibles
load_dotenv(BASE_DIR / '.env')


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Failure to load {name} from .env file.")
    return value


API_HOST: str = _require_env("API_HOST")
API_PORT: int = int(_require_env("API_PORT"))
DB_URL: str = _require_env("DB_URL")
ENTRA_TENANT_ID: str = _require_env("ENTRA_TENANT_ID")
ENTRA_CLIENT_ID: str = _require_env("ENTRA_CLIENT_ID")
ENTRA_CLIENT_SECRET: str = _require_env("ENTRA_CLIENT_SECRET")
ENTRA_REDIRECT_URI: str = _require_env("ENTRA_REDIRECT_URI")
SESSION_SECRET: str = _require_env("SESSION_SECRET")

FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")

LOG_LEVEL = os.getenv("LOG_LEVEL", 'info')

VALID_ENVIRONMENTS = {"dev", "staging", "prod"}
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")
if ENVIRONMENT not in VALID_ENVIRONMENTS:
    raise ValueError(
        f"Invalid ENVIRONMENT '{ENVIRONMENT}', expected one of {VALID_ENVIRONMENTS}."
    )


# Hold the current request id in a context to tag to every log emitted for a request.
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
    """Configure the root logger once at startup.

    dev/staging log plain text for readability; prod logs one JSON object
    per line so CloudWatch Logs Insights can query fields directly.
    """
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
