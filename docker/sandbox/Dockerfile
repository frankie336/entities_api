# -------------------------
# MULTI-STAGE DOCKERFILE (SANDBOX)
# -------------------------

# === Stage 0: base layer (common bootstrap) ============================================
FROM python:3.11-slim AS base
WORKDIR /install

RUN pip install --upgrade pip setuptools wheel

# === Stage 1: install UNHASHED packages (small ones, if any) ============================
FROM base AS unhashed_builder

COPY sandbox_unhashed_reqs.txt .

RUN pip install \
    --prefix=/install/packages \
    #--no-cache-dir \
    --default-timeout=600 \
    --retries 10 \
    -r sandbox_unhashed_reqs.txt

# === Stage 2: install HASHED stable packages ============================================
FROM base AS hashed_builder

COPY sandbox_hashed_reqs.txt .

RUN pip install \
    --prefix=/install/packages \
    --require-hashes \
    #--no-cache-dir \
    --default-timeout=600 \
    --retries 10 \
    -r sandbox_hashed_reqs.txt

# === Stage 3: runtime container =========================================================
FROM python:3.11-slim AS sandbox-runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1

# --- Install minimal OS dependencies needed for sandbox operations ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    firejail \
    supervisor \
    sudo \
    curl \
    wget \
    vim \
    nano \
    less \
    net-tools \
    iproute2 \
    man-db \
    locales \
    htop \
    iputils-ping \
    nmap \
    netcat-openbsd \
    dnsutils \
    tcpdump \
    whois \
    traceroute \
    procps \
    git \
    build-essential \
    libjpeg-dev \
    libpng-dev \
    libfreetype6-dev \
    libopenblas-dev \
    liblapack-dev \
    libxml2-dev \
    libxslt1-dev \
    libffi-dev \
    libmagic1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# --- Create a restricted sandbox user ---
RUN useradd -ms /bin/bash sandboxuser && \
    echo "sandboxuser ALL=(ALL) NOPASSWD: /usr/bin/firejail /bin/bash, /usr/bin/firejail /usr/bin/apt-get *, /usr/bin/firejail /usr/bin/pip" > /etc/sudoers.d/sandboxuser && \
    chmod 440 /etc/sudoers.d/sandboxuser

# --- Prepare app directory ---
RUN mkdir -p /app /var/log/supervisor && chown -R sandboxuser:sandboxuser /app /var/log/supervisor

# --- Copy both unhashed and hashed installed packages ---
COPY --from=unhashed_builder /install/packages /usr/local
COPY --from=hashed_builder /install/packages /usr/local

# --- Copy sandbox app code ---
COPY src/api/sandbox /app/sandbox

# --- Utilities ---
COPY docker/common/wait-for-it.sh /app/wait-for-it.sh
COPY docker/sandbox/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN chmod +x /app/wait-for-it.sh

# --- Expose sandbox FastAPI server port ---
EXPOSE 8000

# --- Default command ---
CMD ["/usr/bin/supervisord", "-n"]
