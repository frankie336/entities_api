# Use the official MySQL image
FROM mysql:8.0

# Set the working directory
WORKDIR /docker-entrypoint-initdb.d/

# Copy any SQL files or scripts for initialization
COPY ./sql-scripts/ .

# Expose the default MySQL port
EXPOSE 3306

# The CMD instruction is not needed as it's provided by the base image