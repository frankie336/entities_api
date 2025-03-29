FROM python:3.8-slim

ENV PYTHONUNBUFFERED=1

# Install system dependencies for pandas, matplotlib, docx support, and sandboxing tooling
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

# Create non-root sandbox user
RUN useradd -ms /bin/bash sandboxuser

# Allow limited sudo access for firejail
RUN echo "sandboxuser ALL=(ALL) NOPASSWD: /usr/bin/firejail /bin/bash, /usr/bin/firejail /usr/bin/apt-get *, /usr/bin/firejail /usr/bin/pip" > /etc/sudoers.d/sandboxuser \
    && chmod 440 /etc/sudoers.d/sandboxuser

# Prepare application directories
RUN mkdir -p /app /var/log/supervisor && chown -R sandboxuser:sandboxuser /app /var/log/supervisor

# Set working directory
WORKDIR /app

# Copy source
COPY src/api/sandbox/requirements.txt /app/
COPY src/api/sandbox/ /app/sandbox/

# Upgrade pip and install Python deps (pandas, matplotlib, docx support should be listed in requirements.txt)
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir --default-timeout=100 -r /app/requirements.txt

# wait-for-it utility
COPY docker/common/wait-for-it.sh /app/wait-for-it.sh
RUN chmod +x /app/wait-for-it.sh

# Supervisor config
COPY docker/sandbox/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8000

CMD ["/usr/bin/supervisord", "-n"]
