import time
from entities_api.new_clients.client import OllamaClient
from entities_api.schemas import ToolFunction, ToolUpdate
from datetime import datetime  # Import the correct datetime class

client = OllamaClient()


user = client.user_service.create_user(name='test_case')

userid = user.id

thread = client.thread_service.create_thread(participant_ids=[userid], meta_data={"topic": ""})
thread_id = thread.id

run = client.run_service.create_run(assistant_id='asst_pwzRlijT9aLPWvet21qIfa',
                                    thread_id = thread_id,


                                    )



action = client.actions_service.create_action(
    tool_name="get_flight_times",
    run_id=run['id'],
    function_args={"departure": "NYC", "arrival": "LAX"},
    expires_at=''
)

action_id = action.id
print(action_id)



update = client.actions_service.update_action(
    action_id=action_id,
    status='complete'
)

