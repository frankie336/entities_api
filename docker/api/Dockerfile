# Use a minimal Python base image
FROM python:3.8-slim

# Install necessary packages including Supervisor, Firejail, and other tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    firejail \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the requirements and install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt

# Copy the API source into /app/api
COPY src/api /app/api

# Set PYTHONPATH so that modules under /app/api are importable (e.g. entities_api)
ENV PYTHONPATH=/app/api

# Copy the wait-for-it.sh script from docker/common to /app and ensure it is executable.
COPY docker/common/wait-for-it.sh /app/wait-for-it.sh

RUN chmod +x /app/wait-for-it.sh

# Copy the unified startup script and ensure it is executable.
COPY docker/api/init_and_run_api.sh /app/init_and_run_api.sh
RUN chmod +x /app/init_and_run_api.sh

# Copy the Supervisor configuration from your build context into the container.
# (Adjust the source path if your supervisord.conf is located elsewhere.)
COPY docker/api/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose the FastAPI port (9000) so external clients can reach your service.
EXPOSE 9000

# Start Supervisor in the foreground so that the container remains running.
CMD ["/usr/bin/supervisord", "-n"]
