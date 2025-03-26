# Use a minimal Python base image
FROM python:3.8-slim

# Install necessary packages (Firejail removed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sudo \
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
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -ms /bin/bash sandboxuser

# Configure passwordless sudo (removed Firejail references)
RUN echo "sandboxuser ALL=(ALL) NOPASSWD: /usr/bin/apt-get *, /usr/bin/pip" > /etc/sudoers.d/sandboxuser \
    && chmod 440 /etc/sudoers.d/sandboxuser

# Create necessary directories
RUN mkdir -p /app /var/log/supervisor && chown -R sandboxuser:sandboxuser /app /var/log/supervisor

# Set the working directory
WORKDIR /app

# Copy application components
COPY src/api/sandbox/requirements.txt /app/
COPY src/api/sandbox/ /app/sandbox/

# Install Python dependencies
RUN pip install --no-cache-dir --default-timeout=100 -r /app/requirements.txt

# Copy the wait-for-it.sh script
COPY docker/common/wait-for-it.sh /app/wait-for-it.sh
RUN chmod +x /app/wait-for-it.sh

# Update Supervisor configuration (remove Firejail from command)
COPY docker/sandbox/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose the FastAPI port
EXPOSE 8000

# Start Supervisor
CMD ["/usr/bin/supervisord", "-n"]