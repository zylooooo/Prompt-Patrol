# Prompt Patrol — worker

Processes batch uploads. It polls the batches SQS queue and screens each row
by calling `create_check` — the same function `POST /api/checks` calls — so a
batch row and a single check go through identical validation, scoring,
thresholds and storage. See the [repo README](../../README.md) for the full
flow and for running the stack; this file covers the worker only.

The worker has no HTTP surface and no domain logic of its own. If a batch row
needs to behave differently from a single check, change `create_check` in
`apps/api`, not this loop.

## How it shares the API's code

The image is built from the **repo root**, not `apps/worker`: the Dockerfile
copies `apps/api/app/` in next to the worker package and installs both
requirement files. That is why the compose `build.context` is `..`. It also
reads `apps/api/.env`, so it uses the same database, queue URLs and detector
settings as the API — including the desklib overrides.

## The loop

Each pass of `poll_once`:

1. Long-polls the main queue (up to 10 messages, 20 s wait). Each message is
   one CSV row, and each row is processed in its own database session.
2. On success, deletes the message. On any exception, **leaves it on the
   queue**: SQS makes it visible again after the visibility timeout and it is
   retried. Don't catch-and-delete here — the unacked message is the retry
   mechanism.
3. Drains the dead-letter queue without waiting. A row that failed
   `maxReceiveCount` times (5, in `apps/api/localstack-init.sh`) lands there,
   and the worker records it as a `batch_row_failure`, so the batch shows that
   row as `failed` instead of `pending` forever.

**Cancelled batches.** Cancelling a batch performs best-effort purging of its
messages from the queue,but a purge can miss messages already in flight. So
before scoring, the worker checks whether the row's batch is cancelled; if it
is, it records a failure ("Batch cancelled by instructor.") and skips the
detector call.

Rows are scored one at a time — both because the loop is sequential and
because the detector serialises scoring. A large batch takes roughly rows ×
per-answer scoring time.

## Configuration

From `apps/api/.env`: `DB_URL`, `AWS_REGION`, `AWS_ENDPOINT_URL`,
`SQS_BATCHES_QUEUE_URL`, `SQS_BATCHES_DLQ_URL` and `DETECTOR_URL`, plus
everything the API's `settings.py` requires, since the worker imports it.

## Tests

The tests import the API's code, so set up the API first:

```sh
pip install -r ../api/requirements.txt -r requirements.txt
pytest
```

`apps/api/.env` must be filled in — the API's `settings.py` loads it on import,
and a missing variable fails the test run before any test starts. The tests
use an in-memory SQLite database and a mocked SQS client.

**These tests are not run in CI yet.** The `unit-tests` job only runs in
`apps/api`, so a change to `create_check` or the models that breaks the worker
will not fail the build. Run them by hand when you touch either.
