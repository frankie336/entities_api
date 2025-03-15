# Dockerfile.sandbox
# Use a minimal Python base image
FROM python:3.8-slim

# Install necessary packages including firejail and basic Linux tools.
RUN apt-get update && apt-get install -y --no-install-recommends \
    firejail \
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
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -ms /bin/bash sandboxuser

# Set the working directory
WORKDIR /app

# Copy only essential components
COPY src/sandbox_api/requirements.txt /app/
COPY src/sandbox_api/ /app/sandbox_api/

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/requirements.txt

# Expose the port for the service
EXPOSE 8000

# Switch to the non-root user for execution
USER sandboxuser

# Run the sandbox server with firejail to limit network access
CMD ["firejail", "--noprofile", "--no-private", "--net=eth0", "uvicorn", "sandbox_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
