FROM python:3.10-slim-bookworm@sha256:ac7bf2ae912299e41783a8e4eff07369dc6de3444bdc1cc29626a05241f957d7 AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  gcc \
  python3-dev \
  && rm -rf /var/lib/apt/lists/*

COPY services/toolbox/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --target=/dependencies -r requirements.txt

# --- Final Stage ---
FROM python:3.10-slim-bookworm@sha256:ac7bf2ae912299e41783a8e4eff07369dc6de3444bdc1cc29626a05241f957d7

WORKDIR /app

# Prevent python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy installed dependencies from builder
COPY --from=builder /dependencies /usr/local/lib/python3.10/site-packages/

# Pre-Bake Embedding Model
ARG EMBEDDING_MODEL_NAME=intfloat/multilingual-e5-large
ENV EMBEDDING_MODEL_NAME=${EMBEDDING_MODEL_NAME}
ENV HF_HOME=/app/data/cache/huggingface

COPY services/shared/scripts/download_model.py /app/download_model.py
RUN python /app/download_model.py && rm /app/download_model.py && chmod -R 777 /app/data/cache

# Create logs directory
RUN mkdir -p /app/data/logs && chmod 777 /app/data/logs

# We copy src to /app/src so imports work cleanly
COPY services/toolbox/src/ ./src/

# Set PYTHONPATH so scripts can import from sibling modules if needed
ENV PYTHONPATH=/app/src

CMD ["tail", "-f", "/dev/null"]
