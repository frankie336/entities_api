#!/bin/bash
set -e  # Exit immediately if any command fails

# Wait for the database to be available
echo "Waiting for database..."
./wait-for-it.sh db:3306 --timeout=30

# Run startup scripts (e.g., necessary initialization tasks)
echo "Running startup scripts..."
python -m entities_api.services.assistant_set_up_service

# Start the FastAPI server using uvicorn
echo "Starting API server..."
exec uvicorn entities_api.main:app --host 0.0.0.0 --port 9000
