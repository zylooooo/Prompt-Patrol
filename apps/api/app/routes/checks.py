import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_role, require_screening_access
from config import request_id_ctx_var
from db import get_db
from models import User, UserRoleEnum
from schemas import CheckListResponse, CheckResponse
from services.checks import (
    DETECTOR_CAPABILITIES,
    THRESHOLDS,
    DetectorTimeoutError,
    DetectorUnavailableError,
    create_check,
    get_check_by_id,
    list_checks,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["checks"])

require_any_user = require_role(UserRoleEnum.teaching_assistant)

# Screening is the one thing an unsupervised assistant may not do. Reading back
# their own past checks is not screening, so the list and fetch routes keep the
# plain session gate - and an assistant loses their sessions the moment someone
# unassigns them anyway, so there is no live reader to shut out.
require_screening = require_screening_access


class CheckCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_text: str
    question_text: str | None = None
    external_ref: str | None = Field(default=None, max_length=128)
    strictness: str = "standard"
    retain_answer: bool = True
    # A batch is rows sharing an id the client assigns; the server has no batch
    # concept of its own. The file name rides along so history can name the run.
    batch_id: uuid.UUID | None = None
    batch_file_name: str | None = Field(default=None, max_length=255)


def _error(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "message": message, "request_id": request_id_ctx_var.get()},
    )


@router.get("/detector")
async def get_detector_capabilities(user: User = Depends(require_any_user)):
    return DETECTOR_CAPABILITIES


@router.post("/checks", status_code=201, response_model=CheckResponse)
async def create_check_route(
    body: CheckCreateRequest,
    response: Response,
    user: User = Depends(require_screening),
    db: AsyncSession = Depends(get_db),
):
    if body.strictness not in THRESHOLDS:
        return _error(400, "invalid_request", f"strictness must be one of {sorted(THRESHOLDS)}.")

    answer_text = body.answer_text
    if len(answer_text) > 10000:
        return _error(413, "payload_too_large", "answer_text exceeds 10,000 characters.")
    if len(answer_text) < 10:
        return _error(400, "invalid_request", "answer_text must be at least 10 characters.")

    try:
        check = await create_check(
            db,
            actor_id=user.id,
            answer_text=answer_text,
            question_text=body.question_text,
            external_ref=body.external_ref,
            strictness=body.strictness,
            retain_answer=body.retain_answer,
            batch_id=body.batch_id,
            batch_file_name=body.batch_file_name,
        )
    except DetectorTimeoutError:
        return _error(504, "detector_timeout", "Detector exceeded the 10s budget.")
    except DetectorUnavailableError:
        logger.exception("Detector call failed.")
        return _error(503, "detector_unavailable", "The detector is temporarily unavailable.")

    # Now points at a route that exists.
    response.headers["Location"] = f"/api/checks/{check.id}"
    return CheckResponse.of(check)


@router.get("/checks", response_model=CheckListResponse)
async def list_checks_route(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
    user: User = Depends(require_any_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own checks, newest first. A root admin sees everyone's -
    checks carry student answer text, so nobody else does."""
    try:
        items, next_cursor = await list_checks(db, user, limit, cursor)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")
    return CheckListResponse(items=[CheckResponse.of(c) for c in items], next_cursor=next_cursor)


@router.get("/checks/{check_id}", response_model=CheckResponse)
async def get_check_route(
    check_id: uuid.UUID,
    user: User = Depends(require_any_user),
    db: AsyncSession = Depends(get_db),
):
    """404 for both "no such check" and "not yours", so this cannot be used to
    discover that someone else's check exists."""
    check = await get_check_by_id(db, user, check_id)
    if check is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Check not found")
    return CheckResponse.of(check)
