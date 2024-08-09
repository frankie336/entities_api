import pytest
import os
from entities.run_client import RunService
from entities.thread_client import ThreadService
from entities.assistant_client import AssistantService
from entities.user_client import UserService  # Assuming UserService exists

base_url = "http://localhost:8000"
api_key = os.getenv("API_KEY")  # Make sure to set this in your environment

run_service = RunService(base_url, api_key)
thread_service = ThreadService(base_url, api_key)
assistant_service = AssistantService(base_url, api_key)
user_service = UserService(base_url, api_key)  # Assuming UserService exists


@pytest.fixture
def create_users():
    user1 = user_service.create_user(name="User 1")
    user2 = user_service.create_user(name="User 2")
    return [user1, user2]


@pytest.fixture
def create_thread(create_users):
    participant_ids = [user["id"] for user in create_users]
    return thread_service.create_thread(participant_ids=participant_ids, meta_data={"topic": "Test Thread"})


@pytest.fixture
def create_assistant():
    return assistant_service.create_assistant(
        name="Math Tutor",
        description="A bot to help solve math problems.",
        model="gpt-4",
        instructions="You are a personal math tutor. Write and run code to answer math questions.",
        tools=[{"type": "code_interpreter"}]
    )


def test_create_run(create_thread, create_assistant):
    thread_id = create_thread["id"]
    assistant_id = create_assistant["id"]
    instructions = "Solve the equation and provide the solution."

    run = run_service.create_run(assistant_id=assistant_id, thread_id=thread_id, instructions=instructions,
                                 meta_data={"context": "math problem"})

    assert run["thread_id"] == thread_id
    assert run["assistant_id"] == assistant_id
    assert run["instructions"] == instructions
    assert "id" in run
    assert "created_at" in run
