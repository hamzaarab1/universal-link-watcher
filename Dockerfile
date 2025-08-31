# Playwright image includes Chromium + all OS deps
FROM mcr.microsoft.com/playwright/python:v1.54.0-noble

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV PORT=8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
