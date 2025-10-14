# -------------------------
# MULTI-STAGE DOCKERFILE
# -------------------------

# === Stage 0: base layer ===============================================================
FROM python:3.11-slim AS base
WORKDIR /install

RUN pip install --upgrade pip setuptools wheel

# === Stage 1: install UNHASHABLE packages (PyTorch, Nvidia, etc.) ======================
FROM base AS unhashed_builder
COPY api_unhashed_reqs.txt .
RUN echo "opencv-python-headless" >> api_unhashed_reqs.txt
RUN pip install \
    --prefix=/install/packages \
    --no-cache-dir \
    --default-timeout=3600 \
    --retries 20 \
    --extra-index-url https://download.pytorch.org/whl/cu121 \
    -r api_unhashed_reqs.txt

# === Stage 2: install HASHED stable trusted packages ===================================
FROM base AS hashed_builder
COPY api_reqs_hashed.txt .
RUN pip install \
    --prefix=/install/packages \
    --require-hashes \
    --no-cache-dir \
    --default-timeout=3600 \
    --retries 20 \
    -r api_reqs_hashed.txt


# === Stage 3: runtime container ========================================================
FROM python:3.11-slim AS runtime
WORKDIR /app

# Minimal OS deps (+ dos2unix)
RUN apt-get update && \
    apt-get install -y --no-install-recommends --no-install-suggests \
        libgl1 \
        libglib2.0-0 \
        libmagic1 \
        firejail \
        supervisor \
        curl \
        wget \
        vim \
        nano \
        git \
        dos2unix && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy both unhashed and hashed installed packages
COPY --from=unhashed_builder /install/packages /usr/local
COPY --from=hashed_builder   /install/packages /usr/local

# ------------------------------------------------------------------
# CHANGED: copy the entire 'src' tree (now contains api/entities_api)
# ------------------------------------------------------------------
COPY src /app/src

# Copy Alembic files to the WORKDIR
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations

# Runtime scripts & config
COPY docker/api/init_and_run_api.sh /app/init_and_run_api.sh
COPY docker/api/supervisord.conf    /etc/supervisor/conf.d/supervisord.conf

# Fix line endings on the remaining script and make it executable
RUN dos2unix /app/init_and_run_api.sh && chmod +x /app/init_and_run_api.sh

# ------------------------------------------------------------------
# CHANGED: point PYTHONPATH at /app/src/api
#   • /app/src/api  ⟶  contains the package `entities_api`
#   • makes `from entities_api.utils import safe_ddl` work in Alembic
# ------------------------------------------------------------------
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src/api

EXPOSE 9000

ENTRYPOINT ["/app/init_and_run_api.sh"]
CMD        ["/usr/bin/supervisord", "-n"]
