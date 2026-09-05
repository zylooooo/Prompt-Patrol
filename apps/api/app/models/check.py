import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class VerdictEnum(str, enum.Enum):
    ai_generated = "ai_generated"
    human_written = "human_written"
    uncertain = "uncertain"


class StrictnessEnum(str, enum.Enum):
    lenient = "lenient"
    standard = "standard"
    strict = "strict"


class AbstainReasonEnum(str, enum.Enum):
    """Why a score was not turned into a verdict. NULL means it was."""

    answer_too_short = "answer_too_short"
    score_in_abstention_band = "score_in_abstention_band"


class Check(Base):
    """
    Each Check stores a screening result for a single answer.
    """

    __tablename__ = "checks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # The author. Reads are scoped to this - see services/checks.list_checks.
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    # Client-assigned grouping for a CSV run. There is no `batches` table: a
    # batch is these rows sharing an id, which is all any screen needs.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # The uploaded file's name, repeated on every row of the run. Denormalised
    # on purpose: it is the only part of a batch that cannot be derived from
    # its rows (the id, timestamp, strictness and counts all can), and a
    # `batches` table whose sole column was a name the client chose would be a
    # second source of truth for grouping.
    batch_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    verdict: Mapped[VerdictEnum] = mapped_column(Enum(VerdictEnum, native_enum=False), nullable=False)
    raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    abstain_reason: Mapped[AbstainReasonEnum | None] = mapped_column(
        Enum(AbstainReasonEnum, native_enum=False), nullable=True
    )
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Flattened `detector` block. The API re-nests it on the way out, because
    # that is the shape the SPA reads.
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    calibration_version: Mapped[str | None] = mapped_column(String, nullable=True)
    strictness_applied: Mapped[StrictnessEnum] = mapped_column(
        Enum(StrictnessEnum, native_enum=False), nullable=False
    )
    threshold_applied: Mapped[float] = mapped_column(Float, nullable=False)
    target_fpr: Mapped[float | None] = mapped_column(Float, nullable=True)
    used_question_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # NULL when the submitter passed `retain_answer: false`. The row is still
    # written - the judgement happened, and a history with holes in it is worse
    # than one that says "the text was not kept".
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Captured at write time, independent of whether answer_text itself is
    # kept - survives a future purge, which answer_text does not.
    answer_char_len: Mapped[int] = mapped_column(Integer, nullable=False)
    retain_answer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The timestamp the check is created, written by the API server, not the database.
    # server_default is kept so that if a row is inserted outside the app, there is
    # still a default value.
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), server_default=func.now()
    )

    __table_args__ = (
        # The history page's only query: this author's checks, newest first,
        # paged by id. Composite because scoping and ordering always travel
        # together here.
        Index("ix_checks_actor_id_created_at", "actor_id", "created_at"),
        Index("ix_checks_batch_id", "batch_id"),
    )
