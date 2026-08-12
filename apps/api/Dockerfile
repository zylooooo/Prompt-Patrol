FROM python:3.13-slim

WORKDIR /app

# Healthcheck in docker-compose.yml runs curl inside this container
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and switch to it
RUN useradd -m -u 1000 apiuser && chown -R apiuser:apiuser /app
USER apiuser
ENV PATH="/home/apiuser/.local/bin:${PATH}"

# Copy application files and requirements
COPY requirements.txt .
COPY app/ /app/
COPY alembic.ini .
COPY alembic/ /app/alembic/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]