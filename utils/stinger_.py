import time
from entities_api.new_clients.client import OllamaClient
from entities_api.schemas import ToolFunction, ToolUpdate
from datetime import datetime  # Import the correct datetime class

client = OllamaClient()





update = client.actions_service.update_action(
    action_id='act_q4Xprv0RhAdX0374xtzGyF',
    status='ready'
)


#get_action = client.actions_service.get_action(action_id=action_id)
#print(status)
#get_action = client.actions_service.get_action(action_id=action_id)
#print(get_action)
#delete_action = client.actions_service.delete_action(action_id=action_id)