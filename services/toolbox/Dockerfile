FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  gcc \
  python3-dev \
  && rm -rf /var/lib/apt/lists/*

COPY services/toolbox/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --target=/dependencies -r requirements.txt

# Test-suite dependencies: the toolbox is the container bin/run_tests.sh runs
# pytest in, so it needs the extras listed in tests/requirements-test.txt
# (e.g. snowballstemmer for rag-proxy's app.py imported by test_rag_proxy.py).
COPY tests/requirements-test.txt /app/requirements-test.txt
RUN pip install --no-cache-dir --target=/dependencies -r requirements-test.txt

# --- Final Stage ---
FROM python:3.14-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

WORKDIR /app

# Prevent python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy installed dependencies from builder
COPY --from=builder /dependencies /usr/local/lib/python3.10/site-packages/


# Create logs directory
RUN mkdir -p /app/data/logs && chmod 777 /app/data/logs

# We copy src to /app/src so imports work cleanly
COPY services/toolbox/src/ ./src/

# Set PYTHONPATH so scripts can import from sibling modules if needed
ENV PYTHONPATH=/app/src

CMD ["tail", "-f", "/dev/null"]
