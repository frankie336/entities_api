#!/bin/bash

# Stop and remove existing containers if they exist
docker stop ollama || true
docker rm ollama || true

# Run the Ollama container with GPU support
docker run -d --gpus=all -v ollama:/root/.ollama -p 11434:11434 --name ollama --network my_custom_network ollama/ollama

# Connect the FastAPI and MySQL containers to the custom network
docker network connect my_custom_network fastapi_cosmic_catalyst
docker network connect my_custom_network my_mysql_cosmic_catalyst
