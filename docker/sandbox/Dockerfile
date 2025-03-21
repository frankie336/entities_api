# Use a minimal Python base image
FROM python:3.8-slim

# Install necessary packages including Supervisor, Firejail, and SSH/Telnet clients.
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
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -ms /bin/bash sandboxuser

# Configure passwordless sudo for sandboxuser with restrictions
RUN echo "sandboxuser ALL=(ALL) NOPASSWD: /usr/bin/firejail /bin/bash, /usr/bin/firejail /usr/bin/apt-get *, /usr/bin/firejail /usr/bin/pip" > /etc/sudoers.d/sandboxuser \
    && chmod 440 /etc/sudoers.d/sandboxuser

# Create necessary directories and adjust permissions; ensure supervisor log directory is writable.
RUN mkdir -p /app /var/log/supervisor && chown -R sandboxuser:sandboxuser /app /var/log/supervisor

# Set the working directory
WORKDIR /app

# Copy application components
COPY src/api/sandbox_api/requirements.txt /app/
COPY src/api/sandbox_api/ /app/sandbox_api/

# Install Python dependencies
RUN pip install --no-cache-dir --default-timeout=100 -r /app/requirements.txt

# Copy the wait-for-it.sh script from docker/common to /app and make it executable.
COPY docker/common/wait-for-it.sh /app/wait-for-it.sh
RUN chmod +x /app/wait-for-it.sh

# Copy Supervisor configuration
# Adjust the source path if your supervisord.conf is located elsewhere (e.g., config/)
COPY docker/sandbox/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose the FastAPI port for server access
EXPOSE 8000

# Start Supervisor in the foreground
CMD ["/usr/bin/supervisord", "-n"]
