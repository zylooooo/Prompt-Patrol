import logging
import os
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Response

from baseline import MODEL_VERSION, status, warm_up
from routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # In a thread rather than inline, so the server can answer /health with
    # "loading" while the model loads. Blocking here would leave the port shut
    # and every caller unable to tell "still starting" from "broken".
    threading.Thread(target=warm_up, name="detector-warmup", daemon=True).start()
    yield


app = FastAPI(
    title="Prompt Patrol Detector",
    description="Stateless AI-text scoring service",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health")
async def health_check(response: Response) -> dict[str, str]:
    """503 until the model is loaded, so compose's health gate means something.

    It previously answered 200 the moment uvicorn bound the port, which let the
    API start against a detector that had not loaded anything - and the first
    real check then paid the whole load cost inside its 10s budget and timed out.
    """
    current = status()
    if current != "ready":
        response.status_code = 503
    return {"status": current, "model_version": MODEL_VERSION}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("DETECTOR_HOST", "0.0.0.0"),
        port=int(os.getenv("DETECTOR_PORT", "8001")),
        log_level="info",
    )
