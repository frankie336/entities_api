# Use the latest MySQL image as the base
FROM mysql:latest

# Copy the entrypoint script to the appropriate directory inside the container
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

# Make the script executable
RUN chmod +x /usr/local/bin/entrypoint.sh

# Override the default entrypoint with our custom entrypoint script
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Start the MySQL daemon
CMD ["mysqld"]
