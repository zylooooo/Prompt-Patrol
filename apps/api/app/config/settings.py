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

LOG_LEVEL = os.getenv("LOG_LEVEL", 'info')

VALID_ENVIRONMENTS = {"dev", "staging", "prod"}
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")
if ENVIRONMENT not in VALID_ENVIRONMENTS:
    raise ValueError(
        f"Invalid ENVIRONMENT '{ENVIRONMENT}', expected one of {VALID_ENVIRONMENTS}."
    )
