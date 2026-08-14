from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware
from config import API_HOST, API_PORT, ENVIRONMENT, LOG_LEVEL, SESSION_SECRET, configure_logging
from db import engine
from middleware import RequestIdMiddleware
from routes import auth_router, users_router
import uvicorn
import sys
import logging

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

# Initialize FastAPI app
# docs/redoc/openapi.json are dev-only, prod shouldn't publicly expose the schema.
_docs_enabled = ENVIRONMENT == "dev"
app = FastAPI(
    title="Prompt Patrol API",
    description="API services for Prompt Patrol",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
# This is Starlette's own signed-cookie session ("ppauthflow"), it only
# carries the OAuth state + PKCE verifier across the Entra redirect. It's not
# the same thing as SESSION_COOKIE_NAME, which is our own post-login session.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="ppauthflow",
    same_site="lax",
    https_only=ENVIRONMENT != "dev",
    max_age=600,
)
app.add_middleware(RequestIdMiddleware)
app.include_router(auth_router)
app.include_router(users_router)

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
