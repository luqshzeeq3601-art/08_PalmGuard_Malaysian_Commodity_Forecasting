FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8000

# Install system dependencies (libgomp1 required for LightGBM OpenMP)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency lock file and install pinned wheels
COPY requirements.lock.txt pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock.txt

# Copy source tree and install palmguard in production mode
COPY src/ ./src/
COPY queries/ ./queries/
COPY config/ ./config/
COPY artifacts/ ./artifacts/
COPY reports/published/ ./reports/published/
RUN pip install --no-cache-dir --no-deps -e .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "palmguard.api:app", "--host", "0.0.0.0", "--port", "8000"]
