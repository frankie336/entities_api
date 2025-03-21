#!/bin/bash
# docker/api/init_and_run_api.sh

set -e  # Exit immediately if any command fails

# Wait for the database to be available using the absolute path
echo "Waiting for database..."
/app/wait-for-it.sh db:3306 --timeout=30

# Run startup scripts (e.g., necessary initialization tasks)
echo "Running startup scripts..."
python -m entities_api.services.assistant_set_up_service

# Start the FastAPI server using uvicorn
echo "Starting API server..."
exec uvicorn entities_api.main:app --host 0.0.0.0 --port 9000
