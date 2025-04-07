# Use a minimal Python base image (Python 3.8 for Pydantic V1 compatibility)
FROM python:3.11-slim

# Set up environment variables
ENV PYTHONUNBUFFERED=1

# Install OS-level dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    firejail \
    supervisor \
    curl \
    wget \
    vim \
    nano \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy Python requirements and install them
COPY requirements.txt /app/

# Upgrade core tools
RUN pip install --upgrade pip setuptools wheel

# Install requirements, using Test PyPI as an extra index for entities_common
RUN pip install --no-cache-dir --default-timeout=100 \
    --index-url https://pypi.org/simple \
    --extra-index-url https://test.pypi.org/simple \
    -r /app/requirements.txt

# Copy API source code
COPY src/api /app/api

# Set PYTHONPATH so FastAPI services work
ENV PYTHONPATH=/app/api

# Wait-for-it script
COPY docker/common/wait-for-it.sh /app/wait-for-it.sh
RUN chmod +x /app/wait-for-it.sh

# API bootstrap script
COPY docker/api/init_and_run_api.sh /app/init_and_run_api.sh
RUN chmod +x /app/init_and_run_api.sh

# Supervisor config
COPY docker/api/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose FastAPI port
EXPOSE 9000

# Run Supervisor
CMD ["/usr/bin/supervisord", "-n"]
