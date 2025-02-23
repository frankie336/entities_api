#!/bin/bash
set -e

# Start the main application first
exec uvicorn entities_api.main:app --host 0.0.0.0 --port 9000 &

# Background initialization
sleep 5  # Give services a moment to stabilize
python -c "
from entities_api.services.initialization_service import AssistantInitializationService
service = AssistantInitializationService()
service.initialize_core_assistant()
"
wait
