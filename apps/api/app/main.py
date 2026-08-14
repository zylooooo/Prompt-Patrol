from config import (
    API_HOST,
    API_PORT,
    DEV_AUTH_ENABLED,
    ENVIRONMENT,
    LOG_LEVEL,
    SESSION_SECRET,
    configure_logging,
)
import sys
import uvicorn
import logging
from db import engine
from fastapi import FastAPI
from sqlalchemy import text
from middleware import RequestIdMiddleware
from routes.auth import router as auth_router
from contextlib import asynccontextmanager
from auth.middleware import SessionAuthMiddleware
from starlette.middleware.sessions import SessionMiddleware

configure_logging()
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

# Initialize the FastAPI application. 
app = FastAPI(
    title="Prompt Patrol API",
    description="API services for Prompt Patrol",
    lifespan=lifespan
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="ppauthflow",
    same_site="lax",
    https_only=ENVIRONMENT != "dev",
    max_age=600,
)
app.add_middleware(SessionAuthMiddleware)
app.add_middleware(RequestIdMiddleware)
app.include_router(auth_router)

if DEV_AUTH_ENABLED:
    from routes.dev_auth import router as dev_auth_router

    app.include_router(dev_auth_router)
    logger.warning(
        "DEV LOGIN ENABLED: /api/auth/dev/* will issue a real session to any "
        "provisioned email with no identity check. Local development only - "
        "keep the API bound to loopback."
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
