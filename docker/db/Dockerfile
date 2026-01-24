# Use the latest MySQL image as the base_workers
FROM mysql:latest

# Copy the correct entrypoint script
COPY docker/db/entrypoint.sh /usr/local/bin/entrypoint.sh

# Make the script executable
RUN chmod +x /usr/local/bin/entrypoint.sh

# Override the default entrypoint with our custom entrypoint script
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Start the MySQL daemon
CMD ["mysqld"]
