#!/bin/bash

# Create the directory if it does not exist
mkdir -p "${HOME}/.ollama/mysql_data"

# Adjust permissions if necessary
chmod 755 "${HOME}/.ollama/mysql_data"

# Execute the default entrypoint for MySQL
exec docker-entrypoint.sh "$@"
