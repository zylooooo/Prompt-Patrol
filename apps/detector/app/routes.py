from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from baseline import calibration, score_text

router = APIRouter()


class ScoreRequest(BaseModel):
    text: str


class ScoreResponse(BaseModel):
    raw_score: float
    truncated: bool
    # What produced raw_score and how to read it (baseline.calibration()). threshold and abstention_band are None for
    # an uncalibrated model, so the API falls back to its own defaults.
    model_version: str
    calibration_version: str | None
    threshold: float | None
    abstention_band: float | None


@router.post("/score", response_model=ScoreResponse)
async def score(body: ScoreRequest) -> ScoreResponse:
    result = await run_in_threadpool(score_text, body.text)
    return ScoreResponse(raw_score=result.raw_score, truncated=result.truncated, **calibration())
