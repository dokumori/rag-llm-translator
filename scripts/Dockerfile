FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ingest.py .
# Default command runs ingestion, but we can override it
CMD ["python", "ingest.py"]
