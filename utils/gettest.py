import time
from entities_api.new_clients.client import OllamaClient
from entities_api.schemas import ToolFunction, ToolUpdate
from datetime import datetime  # Import the correct datetime class

client = OllamaClient()

# Ensure you reference `datetime` correctly here
action = client.actions_service.create_action(
    tool_name="flight_search_tool",
    run_id="run_123456",
    function_args={"departure": "NYC", "arrival": "LAX"},
    expires_at=datetime.now()  # Use datetime.datetime.now() if there's any issue
)
print(action.id)