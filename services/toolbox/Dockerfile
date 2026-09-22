FROM python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS builder

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


# Create logs directory
RUN mkdir -p /app/data/logs && chmod 777 /app/data/logs

# We copy src to /app/src so imports work cleanly
COPY services/toolbox/src/ ./src/

# Set PYTHONPATH so scripts can import from sibling modules if needed
ENV PYTHONPATH=/dependencies:/app/src

CMD ["tail", "-f", "/dev/null"]
