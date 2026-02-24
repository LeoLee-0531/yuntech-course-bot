FROM python:3.12-slim-bookworm

# Install system dependencies:
# - build-essential: C compiler required by python-bidi (easyocr dep) and others
# - curl: needed for some pip/rust tooling
# - libglib2.0-0, libsm6, libxext6, libxrender-dev: required by OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Install dependencies using uv
# We copy the lockfile and pyproject.toml first to leverage Docker caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY app/ ./app/

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV CRON_INTERVAL_SECONDS=30

# users.json is mounted at runtime via docker-compose volume (contains credentials)
CMD ["uv", "run", "python", "-m", "app.main"]
