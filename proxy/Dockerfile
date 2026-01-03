FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
# We do not copy system_prompt.md here; we mount it via Docker Compose
CMD ["python", "app.py"]
