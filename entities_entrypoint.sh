#!/bin/bash
set -e  # Exit immediately if any command fails

# Wait for database
echo "Waiting for database..."
./wait-for-it.sh db:3306 --timeout=30

# Run setup script
echo "Running startup scripts..."
python -m entities_api.services.assistant_set_up_service

# Start FastAPI server
echo "Starting API server..."
exec uvicorn entities_api.main:app --host 0.0.0.0 --port 9000