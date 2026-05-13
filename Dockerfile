# =============================================================================
# Dockerfile — NYTimes News Scraper
# =============================================================================
# Base: Python 3.12 slim sobre Debian (compatível com Playwright/Chromium)
#
# Build:
#   docker build -t nytimes-scraper .
#
# Run (modo padrão):
#   docker run --rm \
#     -v $(pwd)/output:/app/output \
#     -v $(pwd)/logs:/app/logs \
#     nytimes-scraper
#
# Run (com config customizada):
#   docker run --rm \
#     -v $(pwd)/output:/app/output \
#     -v $(pwd)/logs:/app/logs \
#     -v $(pwd)/config/config.yaml:/app/config/config.yaml \
#     nytimes-scraper
# =============================================================================

FROM python:3.12-slim

# --- Metadados ---
LABEL maintainer="Eduardo Gameiro <egameiro@gmail.com>"
LABEL description="NYTimes News Scraper — Desafio Técnico One4Tech"
LABEL version="1.0.0"

# Evita prompts interativos durante apt-get
ENV DEBIAN_FRONTEND=noninteractive
# Python: não gera .pyc, saída sem buffer
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# --- Dependências de sistema para o Chromium (Playwright) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libexpat1 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    lsb-release \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# --- Dependências Python (camada cacheável) ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Chromium via Playwright (camada cacheável) ---
# --with-deps garante que dependências de sistema do Playwright também sejam instaladas
RUN playwright install chromium --with-deps

# --- Código-fonte ---
COPY . .

# --- Pastas de saída (criadas no build; sobrescritas pelos volumes em runtime) ---
RUN mkdir -p output/images logs

# Ponto de entrada padrão
CMD ["python", "main.py"]
