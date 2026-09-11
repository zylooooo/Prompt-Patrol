import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_screening_access
from db import get_db
from models import User
from schemas import BatchProgressResponse, BatchResponse
from services import (
    DETECTOR_CAPABILITIES,
    THRESHOLDS,
    cancel_batch,
    create_batch,
    generate_upload_url,
    get_batch_progress,
)

router = APIRouter(prefix="/api", tags=["batches"])

require_screening = require_screening_access


class UploadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(max_length=255)


class UploadUrlResponse(BaseModel):
    upload_url: str
    upload_key: str


class BatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_key: str
    file_name: str = Field(max_length=255)
    strictness: str = "standard"
    retain_answer: bool = True
    column_mapping: dict[str, str] | None = None


@router.post("/batches/upload-url", response_model=UploadUrlResponse)
async def get_upload_url_route(
    body: UploadUrlRequest,
    user: User = Depends(require_screening),
):
    url, key = generate_upload_url(body.file_name, user.id)
    return UploadUrlResponse(upload_url=url, upload_key=key)


@router.post("/batches", status_code=202, response_model=BatchResponse)
async def create_batch_route(
    body: BatchCreateRequest,
    user: User = Depends(require_screening),
    db: AsyncSession = Depends(get_db),
):
    if body.strictness not in THRESHOLDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"strictness must be one of {sorted(THRESHOLDS)}.",
        )
    if not body.upload_key.startswith(f"batches/{user.id}/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="upload_key was not issued to this actor.",
        )

    batch = await create_batch(
        db,
        actor_id=user.id,
        upload_key=body.upload_key,
        file_name=body.file_name,
        strictness=body.strictness,
        retain_answer=body.retain_answer,
        column_mapping=body.column_mapping,
        requires_question_text=DETECTOR_CAPABILITIES["requires_question_text"],
    )
    if batch.row_total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Every row in the file failed validation. Nothing was submitted.",
        )
    return BatchResponse.of(batch)


@router.get("/batches/{batch_id}", response_model=BatchProgressResponse)
async def get_batch_progress_route(
    batch_id: uuid.UUID,
    user: User = Depends(require_screening),
    db: AsyncSession = Depends(get_db),
):
    progress = await get_batch_progress(db, user, batch_id)
    if progress is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return BatchProgressResponse.of(progress)


@router.post("/batches/{batch_id}/cancel", response_model=BatchProgressResponse)
async def cancel_batch_route(
    batch_id: uuid.UUID,
    user: User = Depends(require_screening),
    db: AsyncSession = Depends(get_db),
):
    batch = await cancel_batch(db, user, batch_id)
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    progress = await get_batch_progress(db, user, batch_id)
    return BatchProgressResponse.of(progress)
