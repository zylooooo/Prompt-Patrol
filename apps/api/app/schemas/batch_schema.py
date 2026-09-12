import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from models import Batch, BatchRowFailure, StrictnessEnum


class BatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    batch_id: uuid.UUID
    actor_id: uuid.UUID
    batch_file_name: str
    strictness: StrictnessEnum
    created_at: datetime
    row_total: int
    cancelled_at: datetime | None = None

    @classmethod
    def of(cls, batch: Batch) -> "BatchResponse":
        return cls(
            batch_id=batch.id,
            actor_id=batch.actor_id,
            batch_file_name=batch.batch_file_name,
            strictness=batch.strictness,
            created_at=batch.created_at,
            row_total=batch.row_total,
            cancelled_at=batch.cancelled_at,
        )


class BatchFailureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    external_ref: str | None
    reason: str

    @classmethod
    def of(cls, failure: BatchRowFailure) -> "BatchFailureResponse":
        return cls(row_number=failure.row_number, external_ref=failure.external_ref, reason=failure.reason)


class BatchProgressResponse(BaseModel):
    batch: BatchResponse
    completed: int
    failed: int
    pending: int
    row_total: int
    cancelled: bool
    failures: list[BatchFailureResponse]

    @classmethod
    def of(cls, progress: dict) -> "BatchProgressResponse":
        return cls(
            batch=BatchResponse.of(progress["batch"]),
            completed=progress["completed"],
            failed=progress["failed"],
            pending=progress["pending"],
            row_total=progress["row_total"],
            cancelled=progress["batch"].cancelled_at is not None,
            failures=[BatchFailureResponse.of(f) for f in progress["failures"]],
        )
