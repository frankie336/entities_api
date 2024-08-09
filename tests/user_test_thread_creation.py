from starlette.testclient import TestClient
from api.app import create_test_app
import time

app = create_test_app()
client = TestClient(app)

def create_user(name: str):
    response = client.post("/v1/users", json={"name": name})
    if response.status_code == 200:
        print(f"User '{name}' created successfully: {response.json()}")
        return response.json()
    else:
        print(f"Failed to create user '{name}': {response.status_code} {response.json()}")
        return None

def create_thread(participant_ids: list):
    thread_data = {
        "participant_ids": participant_ids
    }
    response = client.post("/v1/threads", json=thread_data)
    if response.status_code == 200:
        print(f"Thread created successfully: {response.json()}")
        return response.json()
    else:
        print(f"Failed to create thread: {response.status_code} {response.json()}")
        return None

def create_message(thread_id: str, content: list, role: str, sender_id: str):
    message_data = {
        "content": content,
        "role": role,
        "thread_id": thread_id,
        "sender_id": sender_id,  # Add sender_id to the message data
        "meta_data": {}
    }
    response = client.post("/v1/messages", json=message_data)
    if response.status_code == 200:
        print(f"Message created successfully: {response.json()}")
    else:
        print(f"Failed to create message: {response.status_code} {response.json()}")

def create_run(assistant_id: str, thread_id: str, instructions: str):
    run_data = {
        "id": "run_" + assistant_id + "_" + thread_id,
        "assistant_id": assistant_id,
        "thread_id": thread_id,
        "instructions": instructions,
        "cancelled_at": None,
        "completed_at": None,
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + 3600,  # Set to 1 hour later
        "failed_at": None,
        "incomplete_details": None,
        "last_error": None,
        "max_completion_tokens": 1000,
        "max_prompt_tokens": 500,
        "meta_data": {},
        "model": "gpt-4",
        "object": "run",
        "parallel_tool_calls": False,
        "required_action": None,
        "response_format": "text",
        "started_at": None,
        "status": "pending",
        "tool_choice": "none",
        "tools": [],
        "truncation_strategy": {},
        "usage": None,
        "temperature": 0.7,
        "top_p": 0.9,
        "tool_resources": {}
    }
    response = client.post("/v1/runs", json=run_data)
    if response.status_code == 200:
        print(f"Run created successfully: {response.json()}")
        return response.json()
    else:
        print(f"Failed to create run: {response.status_code} {response.json()}")
        return None

def get_run(run_id: str):
    response = client.get(f"/v1/runs/{run_id}")
    if response.status_code == 200:
        print(f"Run retrieved successfully: {response.json()}")
        return response.json()
    else:
        print(f"Failed to retrieve run: {response.status_code} {response.json()}")
        return None

def create_assistant(name: str, description: str, model: str, instructions: str, tools: list):
    assistant_data = {
        "name": name,
        "description": description,
        "model": model,
        "instructions": instructions,
        "tools": tools,
        "meta_data": {},
        "top_p": 1.0,
        "temperature": 1.0,
        "response_format": "auto"
    }
    response = client.post("/v1/assistants", json=assistant_data)
    if response.status_code == 200:
        print(f"Assistant '{name}' created successfully: {response.json()}")
        return response.json()
    else:
        print(f"Failed to create assistant '{name}': {response.status_code} {response.json()}")
        return None

if __name__ == "__main__":
    # Create users
    user1 = create_user("User 1")
    user2 = create_user("User 2")

    # Ensure users are created
    if user1 and user2:
        # Create a thread with the created users
        thread = create_thread([user1['id'], user2['id']])
        if thread:
            # Create a message in the thread
            content = [{
                "text": {
                    "annotations": [],
                    "value": "I need to solve the equation `3x + 11 = 14`. Can you help me?"
                },
                "type": "text"
            }]
            create_message(thread['id'], content, "user", user1['id'])  # Pass user1's id as sender_id

            # Create an assistant
            tools = [{"type": "file_search"}]
            assistant = create_assistant("Math Assistant", "A bot to help solve math problems.", "gpt-4", "Help solve math problems.", tools)
            if assistant:
                # Create a run
                instructions = "Solve the equation and provide the solution."
                run = create_run(assistant['id'], thread['id'], instructions)

                if run:
                    # Retrieve the created run
                    get_run(run['id'])
                else:
                    print("Could not create run. Aborting.")
            else:
                print("Could not create assistant. Aborting run creation.")
        else:
            print("Could not create thread. Aborting message and run creation.")
    else:
        print("Could not create users. Aborting thread, message, and run creation.")
