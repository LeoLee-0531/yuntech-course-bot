FROM python:3.12-slim-bookworm

# 安裝系統依賴：
# - build-essential: 編譯元件 (easyocr 依賴)
# - curl: uv 需要
# - libglib2.0-0, libsm6, libxext6, libxrender-dev: OpenCV 依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# 安裝 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 啟用位元組碼編譯
ENV UV_COMPILE_BYTECODE=1

# 使用 uv 安裝依賴
# 先複製設定檔以利用快取
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

# 複製程式碼
COPY app/ ./app/

# 環境變數
ENV PYTHONUNBUFFERED=1
ENV CRON_INTERVAL_SECONDS=30

# 帳密資訊由 docker-compose 掛載掛載運行時掛載
CMD ["uv", "run", "python", "-m", "app.main"]
