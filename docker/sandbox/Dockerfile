# Use a minimal Python base image
FROM python:3.8-slim

# Install necessary packages including firejail, basic Linux tools, and penetration testing tools.
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
    iputils-ping \
    nmap \
    netcat-openbsd \
    dnsutils \
    tcpdump \
    whois \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && git clone https://github.com/sullo/nikto.git /opt/nikto \
    && ln -s /opt/nikto/program/nikto.pl /usr/local/bin/nikto \
    && chmod +x /usr/local/bin/nikto

# Create a non-root user
RUN useradd -ms /bin/bash sandboxuser

# Set the working directory
WORKDIR /app

# Copy only the essential components from the sandbox_api package.
COPY src/api/sandbox_api/requirements.txt /app/
COPY src/api/sandbox_api/ /app/sandbox_api/

# Install Python dependencies using the copied requirements file.
RUN pip install --no-cache-dir --default-timeout=100 -r /app/requirements.txt

# Expose the port for the FastAPI service
EXPOSE 8000

# Switch to the non-root user for execution
USER sandboxuser

# Set the CMD to run the sandbox server using uvicorn under firejail restrictions.
CMD ["firejail", "--noprofile", "--no-private", "--net=eth0", "uvicorn", "sandbox_api.main:app", "--host", "0.0.0.0", "--port", "8000"]