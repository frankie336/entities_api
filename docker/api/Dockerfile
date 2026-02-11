# -------------------------
# MULTI-STAGE DOCKERFILE
# -------------------------

# === Stage 0: base layer ===============================================================
FROM python:3.11-slim-bookworm AS base
WORKDIR /install

RUN pip install --upgrade pip setuptools wheel


# === Stage 1: install UNHASHED packages ===============================================
FROM base AS unhashed_builder
COPY api_unhashed_reqs.txt .

# ensure opencv present if not listed
RUN echo "opencv-python-headless" >> api_unhashed_reqs.txt

RUN pip install \
    --prefix=/install/packages \
    --no-cache-dir \
    --default-timeout=100 \
    --retries 10 \
    -r api_unhashed_reqs.txt


# === Stage 2: install HASHED stable trusted packages ===================================
FROM base AS hashed_builder
COPY api_reqs_hashed.txt .

RUN pip install \
    --prefix=/install/packages \
    --require-hashes \
    --no-cache-dir \
    --default-timeout=100 \
    --retries 10 \
    -r api_reqs_hashed.txt


# === Stage 3: runtime container ========================================================
FROM python:3.11-slim-bookworm AS runtime
WORKDIR /app

# ------------------------------------------------------------------
# SYSTEM DEPENDENCIES
# 1. Remove default .sources file (Fixes "Configured Multiple Times" error)
# 2. Use HTTP mirrors (Fixes "Connection Refused/SSL" bridge issues)
# ------------------------------------------------------------------
RUN rm -f /etc/apt/sources.list.d/*.sources && \
    printf "deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware\n\
deb http://deb.debian.org/debian bookworm-updates main contrib non-free non-free-firmware\n\
deb http://security.debian.org/debian-security bookworm-security main contrib non-free non-free-firmware\n" \
    > /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libmagic1 \
        firejail \
        supervisor \
        wget \
        vim \
        nano \
        git \
        dos2unix \
        ca-certificates \
        curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


# --- Copy installed packages from builder stages ---
COPY --from=unhashed_builder /install/packages /usr/local
COPY --from=hashed_builder   /install/packages /usr/local


# ------------------------------------------------------------------
# WEB READER DEPENDENCIES
# ------------------------------------------------------------------
# Install Playwright browsers (Chromium only to save space/time)
RUN pip install --no-cache-dir html2text playwright && \
    playwright install --with-deps chromium


# ------------------------------------------------------------------
# Copy Source Code
# ------------------------------------------------------------------
COPY src /app/src

COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations

COPY docker/api/init_and_run_api.sh /app/init_and_run_api.sh
COPY docker/api/supervisord.conf    /etc/supervisor/conf.d/supervisord.conf

# Ensure line endings are correct and script is executable
RUN dos2unix /app/init_and_run_api.sh && chmod +x /app/init_and_run_api.sh


# ------------------------------------------------------------------
# Runtime configuration
# ------------------------------------------------------------------
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src/api

EXPOSE 9000

ENTRYPOINT ["/app/init_and_run_api.sh"]
CMD ["/usr/bin/supervisord", "-n"]