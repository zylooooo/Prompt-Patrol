import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from models import Batch, BatchRowFailure, Check, StrictnessEnum, User, UserRoleEnum, VerdictEnum
from services.checks_service import CHECK_RETENTION, purge_expired_checks


def _check(actor: User, created_at: datetime, batch_id: uuid.UUID | None = None) -> Check:
    return Check(
        id=uuid.uuid4(),
        actor_id=actor.id,
        batch_id=batch_id,
        verdict=VerdictEnum.human_written,
        raw_score=0.1,
        model_version="m",
        strictness_applied=StrictnessEnum.standard,
        threshold_applied=0.5,
        answer_char_len=10,
        created_at=created_at,
    )


def _batch(actor: User, created_at: datetime) -> Batch:
    return Batch(
        id=uuid.uuid4(),
        actor_id=actor.id,
        batch_file_name="f.csv",
        strictness=StrictnessEnum.standard,
        requires_question_text=False,
        row_total=2,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_purge_deletes_history_past_retention_and_whole_batches_only(db_session):
    actor = User(id=uuid.uuid4(), email="r@smu.edu.sg", auth0_sub="oid-r", role=UserRoleEnum.instructor)
    db_session.add(actor)
    await db_session.commit()
    now = datetime.now(UTC)
    old, recent = now - CHECK_RETENTION - timedelta(hours=1), now - CHECK_RETENTION + timedelta(hours=1)

    old_single, kept_single = _check(actor, old), _check(actor, recent)
    old_batch, kept_batch = _batch(actor, old), _batch(actor, recent)
    db_session.add_all([old_single, kept_single, old_batch, kept_batch])
    await db_session.flush()
    # The old batch's last row was scored after the cutoff: it still goes with its batch.
    straddling = _check(actor, recent, old_batch.id)
    kept_batch_row = _check(actor, recent, kept_batch.id)
    db_session.add_all([_check(actor, old, old_batch.id), straddling, kept_batch_row])
    db_session.add(BatchRowFailure(id=uuid.uuid4(), batch_id=old_batch.id, row_number=2, reason="x", created_at=old))
    await db_session.commit()

    assert await purge_expired_checks(db_session, batch_size=1) == (3, 1)

    assert set((await db_session.execute(select(Check.id))).scalars()) == {kept_single.id, kept_batch_row.id}
    assert set((await db_session.execute(select(Batch.id))).scalars()) == {kept_batch.id}
    assert (await db_session.execute(select(BatchRowFailure))).first() is None
    assert await purge_expired_checks(db_session) == (0, 0)


@pytest.mark.asyncio
async def test_purge_pages_through_chunks_and_spares_a_surviving_batch(db_session):
    actor = User(id=uuid.uuid4(), email="s@smu.edu.sg", auth0_sub="oid-s", role=UserRoleEnum.instructor)
    db_session.add(actor)
    await db_session.commit()
    now = datetime.now(UTC)
    old = now - CHECK_RETENTION - timedelta(hours=1)
    kept_batch = _batch(actor, now - CHECK_RETENTION + timedelta(seconds=30))
    old_batches = [_batch(actor, old), _batch(actor, old)]
    db_session.add_all([kept_batch, *old_batches])
    await db_session.flush()
    # Worker clock a minute behind the API's: this row looks old, its batch does not.
    skewed = _check(actor, old, kept_batch.id)
    singles = [_check(actor, old) for _ in range(11)]
    db_session.add_all([skewed, *singles, *(_check(actor, old, b.id) for b in old_batches)])
    await db_session.commit()

    # batch_size=1: two passes of the batch loop, and the single loop's chunk of 10 needs two.
    assert await purge_expired_checks(db_session, batch_size=1) == (13, 2)
    assert set((await db_session.execute(select(Check.id))).scalars()) == {skewed.id}
    assert set((await db_session.execute(select(Batch.id))).scalars()) == {kept_batch.id}
