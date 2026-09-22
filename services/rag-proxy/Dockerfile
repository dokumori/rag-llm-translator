FROM python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  gcc \
  python3-dev \
  && rm -rf /var/lib/apt/lists/*

COPY services/rag-proxy/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --target=/dependencies -r requirements.txt

# --- Final Stage ---
FROM python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56

WORKDIR /app

# Prevent python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy installed dependencies from builder.
# Kept at /dependencies and exposed via PYTHONPATH rather than copied into
# /usr/local/lib/pythonX.Y/site-packages/, so a base-image Python version bump
# cannot silently strand them in a path the new interpreter never reads.
COPY --from=builder /dependencies /dependencies

# --- Embedding Model Download Script ---
# Kept permanently in the image so bin/download-model.sh can invoke it
# to download models into the bind-mounted host cache (data/cache/huggingface/).
# The model is NOT downloaded at build time — run bin/download-model.sh separately.
ENV HF_HOME=/app/data/cache/huggingface
COPY services/shared/scripts/download_model.py /app/download_model.py
COPY services/shared/scripts/check_collection_model.py /app/check_collection_model.py
COPY services/shared/scripts/delete_collections.py /app/delete_collections.py

# Copy source code
COPY services/rag-proxy/src/ ./src/

# Set PYTHONPATH
ENV PYTHONPATH=/dependencies:/app/src

# Run the application
CMD ["python", "src/app.py"]
