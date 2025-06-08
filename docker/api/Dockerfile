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

RUN pip install \
    --prefix=/install/packages \
    --no-cache-dir \
    --default-timeout=1800 \
    --retries 3 0 \
    --extra-index-url https://download.pytorch.org/whl/cu121 \
    -r api_unhashed_reqs.txt

# === Stage 2: install HASHED stable trusted packages ===================================
FROM base AS hashed_builder

COPY api_reqs_hashed.txt .

RUN pip install \
    --prefix=/install/packages \
    --require-hashes \
    --no-cache-dir \
    --default-timeout=1800 \
    --retries 10 \
    -r api_reqs_hashed.txt

# === Stage 3: runtime container ========================================================
FROM python:3.11-slim AS runtime
WORKDIR /app

# Minimal OS deps  (added libmagic1 for python-magic)
RUN apt-get update && \
    apt-get install -y --no-install-recommends --no-install-suggests \
        libmagic1 \
        firejail \
        supervisor \
        curl \
        wget \
        vim \
        nano \
        git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy both unhashed and hashed installed packages
COPY --from=unhashed_builder /install/packages /usr/local
COPY --from=hashed_builder   /install/packages /usr/local

# Application source
COPY src/api /app/api

# Runtime scripts & config
COPY docker/common/wait-for-it.sh       /app/wait-for-it.sh
COPY docker/api/init_and_run_api.sh     /app/init_and_run_api.sh
COPY docker/api/supervisord.conf        /etc/supervisor/conf.d/supervisord.conf
RUN chmod +x /app/wait-for-it.sh /app/init_and_run_api.sh

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/api

EXPOSE 9000

CMD ["/usr/bin/supervisord", "-n"]
