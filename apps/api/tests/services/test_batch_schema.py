import uuid
from datetime import UTC, datetime

from models import Batch, BatchRowFailure, StrictnessEnum
from schemas import BatchProgressResponse, BatchResponse


def _batch() -> Batch:
    return Batch(
        id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        batch_file_name="answers.csv",
        strictness=StrictnessEnum.standard,
        retain_answer=True,
        requires_question_text=False,
        row_total=3,
        created_at=datetime.now(UTC),
    )


def test_batch_response_of():
    batch = _batch()
    response = BatchResponse.of(batch)
    assert response.batch_id == batch.id
    assert response.row_total == 3


def test_batch_progress_response_of():
    batch = _batch()
    failure = BatchRowFailure(
        id=uuid.uuid4(),
        batch_id=batch.id,
        row_number=2,
        external_ref="stu-1",
        reason="answer_text is empty.",
    )
    response = BatchProgressResponse.of(
        {
            "batch": batch,
            "row_total": 3,
            "completed": 1,
            "failed": 1,
            "pending": 1,
            "failures": [failure],
        }
    )
    assert response.completed == 1
    assert response.batch.batch_id == batch.id
    assert [f.model_dump() for f in response.failures] == [
        {"row_number": 2, "external_ref": "stu-1", "reason": "answer_text is empty."}
    ]
