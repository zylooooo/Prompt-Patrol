import logging

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from auth.dependencies import require_role
from config import request_id_ctx_var
from models import User, UserRoleEnum
from services.checks import (
    DETECTOR_CAPABILITIES,
    THRESHOLDS,
    DetectorTimeoutError,
    DetectorUnavailableError,
    create_check,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["checks"])

require_any_user = require_role(UserRoleEnum.teaching_assistant)


class CheckCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str
    question_text: str | None = None
    external_ref: str | None = Field(default=None, max_length=128)
    strictness: str = "standard"
    retain_answer: bool = True


def _error(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "message": message, "request_id": request_id_ctx_var.get()},
    )


@router.get("/detector")
async def get_detector_capabilities(user: User = Depends(require_any_user)):
    return DETECTOR_CAPABILITIES


@router.post("/checks", status_code=201)
async def create_check_route(
    body: CheckCreateRequest,
    response: Response,
    user: User = Depends(require_any_user),
):
    if body.strictness not in THRESHOLDS:
        return _error(400, "invalid_request", f"strictness must be one of {sorted(THRESHOLDS)}.")

    answer_text = body.answer_text
    if len(answer_text) > 10000:
        return _error(413, "payload_too_large", "answer_text exceeds 10,000 characters.")
    if len(answer_text) < 10:
        return _error(400, "invalid_request", "answer_text must be at least 10 characters.")

    try:
        result = await create_check(
            actor_id=user.id,
            answer_text=answer_text,
            question_text=body.question_text,
            external_ref=body.external_ref,
            strictness=body.strictness,
            retain_answer=body.retain_answer,
        )
    except DetectorTimeoutError:
        return _error(504, "detector_timeout", "Detector exceeded the 10s budget.")
    except DetectorUnavailableError:
        logger.exception("Detector call failed.")
        return _error(503, "detector_unavailable", "The detector is temporarily unavailable.")

    response.headers["Location"] = f"/api/checks/{result['check_id']}"
    return result
