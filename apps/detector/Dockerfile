FROM python:3.13-slim

WORKDIR /app

# Healthcheck in docker-compose.yml runs curl inside this container
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and switch to it.
RUN useradd -m -u 1000 detectoruser \
    && mkdir -p /home/detectoruser/.cache/huggingface \
    && chown -R detectoruser:detectoruser /app /home/detectoruser
USER detectoruser
ENV PATH="/home/detectoruser/.local/bin:${PATH}"

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the ~500MB model into the image so startup is a local disk read. Keep the
# name in step with baseline.MODEL_NAME - it cannot be imported from here
# without putting app/ above this layer, which would re-download on every code
# change. HF_HUB_OFFLINE afterwards turns a cache miss into a loud startup
# failure instead of a silent download in production.
ENV HF_HOME=/home/detectoruser/.cache/huggingface
RUN python -c "from transformers import pipeline; \
    pipeline('text-classification', model='openai-community/roberta-base-openai-detector', top_k=None)"
ENV HF_HUB_OFFLINE=1

# Last, so editing the app does not invalidate the layers above it.
COPY app/ /app/

CMD ["python", "main.py"]
