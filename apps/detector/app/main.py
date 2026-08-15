import logging
import os

import uvicorn
from fastapi import FastAPI

from routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Prompt Patrol Detector", description="Stateless AI-text scoring service")
app.include_router(router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("DETECTOR_HOST", "0.0.0.0"),
        port=int(os.getenv("DETECTOR_PORT", "8001")),
        log_level="info",
    )
