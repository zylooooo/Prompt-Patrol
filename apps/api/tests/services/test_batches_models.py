import uuid

import pytest
from sqlalchemy import select

from models import Batch, BatchRowFailure, StrictnessEnum, User, UserRoleEnum


@pytest.mark.asyncio
async def test_batch_and_row_failure_round_trip(db_session):
    user = User(id=uuid.uuid4(), email="instr@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    batch = Batch(
        id=uuid.uuid4(),
        actor_id=user.id,
        batch_file_name="answers.csv",
        strictness=StrictnessEnum.standard,
        retain_answer=True,
        requires_question_text=False,
        row_total=2,
    )
    db_session.add(batch)
    await db_session.commit()

    failure = BatchRowFailure(
        id=uuid.uuid4(),
        batch_id=batch.id,
        row_number=3,
        external_ref="stu-1",
        reason="answer_text is under 10 characters.",
    )
    db_session.add(failure)
    await db_session.commit()

    fetched = (await db_session.execute(select(Batch).where(Batch.id == batch.id))).scalar_one()
    assert fetched.row_total == 2
    fetched_failure = (
        await db_session.execute(select(BatchRowFailure).where(BatchRowFailure.batch_id == batch.id))
    ).scalar_one()
    assert fetched_failure.row_number == 3
