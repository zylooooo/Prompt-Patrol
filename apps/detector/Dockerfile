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

# Copy application files and requirements
COPY requirements.txt .
COPY app/ /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]
