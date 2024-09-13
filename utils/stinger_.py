import time
from entities_api.new_clients.client import OllamaClient
from entities_api.schemas import ToolFunction, ToolUpdate
from datetime import datetime  # Import the correct datetime class

client = OllamaClient()





update = client.actions_service.update_action(
    action_id='act_UakvDNondmrbswmJTjR0xh',
    status='ready'
)

