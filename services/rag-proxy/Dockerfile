FROM python:3.10-slim

WORKDIR /app

# Install dependencies first (caching layer)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY services/rag-proxy/src/ .

# Run the application
CMD ["python", "app.py"]
