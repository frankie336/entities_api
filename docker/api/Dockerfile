# Use a minimal Python base image (Upgraded to Python 3.11 for better compatibility)
FROM python:3.11-slim

# Set up environment variables to avoid Python buffering issues
ENV PYTHONUNBUFFERED=1

# Install necessary system dependencies
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

# Copy the requirements file and install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt


# Copy the API source into /app/api
COPY src/api /app/api

# Set PYTHONPATH so that modules under /app/api are importable (e.g. entities)
ENV PYTHONPATH=/app/api

# Copy the wait-for-it.sh script and ensure it is executable
COPY docker/common/wait-for-it.sh /app/wait-for-it.sh
RUN chmod +x /app/wait-for-it.sh

# Copy the unified startup script and ensure it is executable
COPY docker/api/init_and_run_api.sh /app/init_and_run_api.sh
RUN chmod +x /app/init_and_run_api.sh

# Copy the Supervisor configuration
COPY docker/api/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose the FastAPI port (9000)
EXPOSE 9000

# Start Supervisor in the foreground
CMD ["/usr/bin/supervisord", "-n"]
