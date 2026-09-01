FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS builder

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
FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

WORKDIR /app

# Prevent python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy installed dependencies from builder
COPY --from=builder /dependencies /usr/local/lib/python3.10/site-packages/

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
ENV PYTHONPATH=/app/src

# Run the application
CMD ["python", "src/app.py"]
