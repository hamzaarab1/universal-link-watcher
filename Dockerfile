# Base image includes Chromium + all OS deps needed by Playwright
FROM mcr.microsoft.com/playwright/python:v1.54.0-noble

# Ensure logs flush immediately
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY server.py .

# Start the API; use the host-provided $PORT (Render sets this), default 8000 for local
CMD ["bash","-lc","uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
