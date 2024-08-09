from entities.assistant_client import AssistantService
import os

base_url = "http://localhost:8000"
api_key = os.getenv("API_KEY")  # Make sure to set this in your environment

assistant_service = AssistantService(base_url, api_key)

def test_create_assistant():
    assistant = assistant_service.create_assistant(
        name="Math Tutor",
        description="A bot to help solve math problems.",
        model="gpt-4",
        instructions="You are a personal math tutor. Write and run code to answer math questions.",
        tools=[{"type": "code_interpreter"}]
    )
    assert assistant["name"] == "Math Tutor"
    assert assistant["description"] == "A bot to help solve math problems."

def test_retrieve_assistant():
    assistant_id = "assistant_id_here"  # Use a real assistant ID
    assistant = assistant_service.retrieve_assistant(assistant_id)
    assert assistant["id"] == assistant_id

# Add more tests for update, list, and delete methods
