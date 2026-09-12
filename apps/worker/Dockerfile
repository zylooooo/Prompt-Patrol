# This image needs apps/api/app's domain logic (checks_service.create_check,
# models, db, config) alongside its own poll loop.
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
