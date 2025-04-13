# -------------------------
# MULTI-STAGE DOCKERFILE
# -------------------------

# === Stage 1: Builder ===
FROM python:3.11-slim AS builder

WORKDIR /install

# Copy the requirements file
COPY requirements.txt .

# Install all dependencies into a temporary directory
RUN pip install --upgrade pip setuptools wheel && \
    pip install --prefix=/install/packages --no-cache-dir --default-timeout=100 \
        --index-url https://pypi.org/simple \
        --extra-index-url https://test.pypi.org/simple \
        -r requirements.txt

# === Stage 2: Runtime ===
FROM python:3.11-slim AS runtime

WORKDIR /app

# OS-level dependencies (minimal, production-focused)
RUN apt-get update && apt-get install -y --no-install-recommends \
    firejail \
    supervisor \
    curl \
    wget \
    vim \
    nano \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install/packages /usr/local

# Copy app source
COPY src/api /app/api

# Runtime scripts and config
COPY docker/common/wait-for-it.sh /app/wait-for-it.sh
COPY docker/api/init_and_run_api.sh /app/init_and_run_api.sh
COPY docker/api/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN chmod +x /app/wait-for-it.sh /app/init_and_run_api.sh

# Environment setup
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/api

# Expose FastAPI port
EXPOSE 9000

# Default CMD
CMD ["/usr/bin/supervisord", "-n"]
