from fastapi import APIRouter
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from baseline import score_text

router = APIRouter()


class ScoreRequest(BaseModel):
    text: str


class ScoreResponse(BaseModel):
    raw_score: float
    truncated: bool


@router.post("/score", response_model=ScoreResponse)
async def score(body: ScoreRequest) -> ScoreResponse:
    result = await run_in_threadpool(score_text, body.text)
    return ScoreResponse(raw_score=result.raw_score, truncated=result.truncated)
