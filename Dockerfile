FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
RUN playwright install-deps chromium
COPY . .
RUN mkdir -p /app/data/hep_podaci /app/data/fs_podaci
ENV DATA_DIR=/app/data
CMD ["python", "server.py"]
