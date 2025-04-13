# -------------------------
# MULTI-STAGE DOCKERFILE
# -------------------------

# === Stage 1: Builder ===
FROM python:3.11-slim AS builder

WORKDIR /install

# Copy requirements and install to isolated path
COPY src/api/sandbox/requirements.txt ./requirements.txt

# Upgrade pip and install dependencies into a temporary location
RUN pip install --upgrade pip setuptools wheel && \
    pip install --prefix=/install/packages --no-cache-dir --default-timeout=100 \
        --index-url https://pypi.org/simple \
        --extra-index-url https://test.pypi.org/simple \
        -r requirements.txt


# === Stage 2: Runtime ===
FROM python:3.11-slim AS sandbox-runtime

ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    sudo \
    firejail \
    supervisor \
    openssh-client \
    telnet \
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
    && rm -rf /var/lib/apt/lists/*

# Create sandbox user
RUN useradd -ms /bin/bash sandboxuser && \
    echo "sandboxuser ALL=(ALL) NOPASSWD: /usr/bin/firejail /bin/bash, /usr/bin/firejail /usr/bin/apt-get *, /usr/bin/firejail /usr/bin/pip" > /etc/sudoers.d/sandboxuser && \
    chmod 440 /etc/sudoers.d/sandboxuser

# Working directories
RUN mkdir -p /app /var/log/supervisor && chown -R sandboxuser:sandboxuser /app /var/log/supervisor

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install/packages /usr/local

# Copy application source code
COPY src/api/sandbox /app/sandbox

# wait-for-it
COPY docker/common/wait-for-it.sh /app/wait-for-it.sh
RUN chmod +x /app/wait-for-it.sh

# Supervisor config
COPY docker/sandbox/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose sandbox port
EXPOSE 8000

# Start the supervisor
CMD ["/usr/bin/supervisord", "-n"]
