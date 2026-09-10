# Build context is the repo root (see apps/docker-compose.yml, Task 9) -
# this image needs apps/api/app's domain logic (checks_service.create_check,
# models, db, config) alongside its own poll loop. Neither app is
# pip-installable today, so this is a plain COPY, not a dependency install -
# see docs/superpowers/specs/2026-09-09-batches-module-design.md Decision 6.
FROM python:3.13-slim

WORKDIR /app

RUN useradd -m -u 1000 workeruser && chown -R workeruser:workeruser /app
USER workeruser
ENV PATH="/home/workeruser/.local/bin:${PATH}"

COPY apps/api/requirements.txt ./api-requirements.txt
COPY apps/worker/requirements.txt ./worker-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt -r worker-requirements.txt

COPY apps/api/app/ /app/
COPY apps/worker/worker/ /app/worker/

CMD ["python", "-m", "worker.main"]
