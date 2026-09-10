import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base
from .check import StrictnessEnum


class Batch(Base):
    """Owns batch job lifecycle/settings. Check rows for a batch are never
    created in a pending state - see checks.batch_id's comment history and
    docs/superpowers/specs/2026-09-09-batches-module-design.md Decision 2.
    Progress is computed, not stored: row_total vs. COUNT(checks) +
    COUNT(batch_row_failures) for this batch_id."""

    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    batch_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    strictness: Mapped[StrictnessEnum] = mapped_column(
        Enum(StrictnessEnum, native_enum=False), nullable=False
    )
    retain_answer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The GET /api/detector capability flag's value, locked in at submission
    # time so a mid-processing detector deploy can't change what a
    # half-finished batch expects.
    requires_question_text: Mapped[bool] = mapped_column(Boolean, nullable=False)
    row_total: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), server_default=func.now()
    )
    # Set once, never cleared. Rows already enqueued before this is set still
    # drain out of SQS - the Worker checks it per-message and records a
    # batch_row_failure instead of scoring, rather than trying to purge
    # in-flight messages. See DECISION LOG [0.14.0].
    cancelled_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)


class BatchRowFailure(Base):
    """A CSV row that failed server-side validation before it ever reached
    SQS, or a message that exhausted SQS redelivery and was drained from the
    DLQ. Append-only, same shape as UserStatusEvent/UserRoleEvent."""

    __tablename__ = "batch_row_failures"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("batches.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), server_default=func.now()
    )

    __table_args__ = (Index("ix_batch_row_failures_batch_id", "batch_id"),)
