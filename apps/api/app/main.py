from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from config import API_HOST, API_PORT, ENVIRONMENT, LOG_LEVEL
from db import engine
import uvicorn
import sys
import logging

logging.basicConfig(
    level=LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Failed to connect to the database on startup.")
        raise
    logger.info("Database connection verified.")
    yield
    await engine.dispose()

# Initialize FastAPI app
app = FastAPI(
    title="Prompt Patrol API",
    description="API services for Prompt Patrol",
    lifespan=lifespan
)

# Health check endpoint
@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint to verify that API is running."""
    return {
        "status": "healthy"
    }

# Run the server
def run_app():
    reload = ENVIRONMENT == "dev"

    try:
        logger.info(f"Starting server in {ENVIRONMENT} mode...")
        uvicorn.run(
            "main:app",
            host=API_HOST,
            port=API_PORT,
            log_level=LOG_LEVEL,
            log_config=None,
            reload=reload,
        )
        logger.info("Server shutdown complete.")
    except Exception:
        logger.exception("An unexpected error occured.")
        sys.exit(1)

if __name__ == "__main__":
    run_app()
