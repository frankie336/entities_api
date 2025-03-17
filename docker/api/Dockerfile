FROM python:3.8-slim

# Set the working directory
WORKDIR /app

# Copy and install Python dependencies from the project root
COPY requirements.txt /app/
RUN pip install --no-cache-dir --default-timeout=100 -r /app/requirements.txt

# Install firejail and other minimal Linux tools (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    firejail \
    && rm -rf /var/lib/apt/lists/*

# Copy the source code folder into the container.
# This assumes your API code is under "src/api", where "entities_api" is a subfolder.
COPY src/api /app/api

# Download the wait-for-it script into /app/
ADD https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh /app/wait-for-it.sh

# Copy the entrypoint script (adjust the path as needed)
COPY docker/api/entities_entrypoint.sh /app/

# Ensure that the wait-for-it and entrypoint scripts are executable.
RUN chmod +x /app/wait-for-it.sh /app/entities_entrypoint.sh

# Set PYTHONPATH so that modules under /app/api (like entities_api) are importable.
ENV PYTHONPATH=/app/api

# Expose the API port (9000 in this case).
EXPOSE 9000

# Run the API using the custom entrypoint script.
CMD ["/app/entities_entrypoint.sh"]
