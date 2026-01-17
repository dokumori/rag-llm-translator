FROM python:3.10-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  gcc \
  python3-dev \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --target=/dependencies -r requirements.txt

# --- Final Stage ---
FROM python:3.10-slim

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
