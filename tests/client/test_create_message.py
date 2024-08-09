import pytest
import os
from entities.message_client import MessageService
from entities.thread_client import ThreadService
from entities.user_client import UserService  # Assuming UserService exists

base_url = "http://localhost:8000"
api_key = os.getenv("API_KEY")  # Make sure to set this in your environment

message_service = MessageService(base_url, api_key)
thread_service = ThreadService(base_url, api_key)
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


def test_create_message(create_thread, create_users):
    thread_id = create_thread["id"]
    user_id = create_users[0]["id"]
    content = [{
        "text": {
            "annotations": [],
            "value": "I need to solve the equation `3x + 11 = 14`. Can you help me?"
        },
        "type": "text"
    }]
    role = "user"
    message = message_service.create_message(thread_id=thread_id, content=content, role=role, sender_id=user_id,
                                             meta_data={"context": "math problem"})

    assert message["thread_id"] == thread_id
    assert message["content"] == content
    assert message["role"] == role
    assert "id" in message
    assert "created_at" in message
