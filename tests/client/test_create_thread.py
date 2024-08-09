import pytest
import os
from entities_api.thread_client import ThreadService

from entities_api.user_client import UserService  # Assume you have a UserService client

base_url = "http://localhost:8000"
api_key = os.getenv("API_KEY")  # Make sure to set this in your environment

thread_service = ThreadService(base_url, api_key)
user_service = UserService(base_url, api_key)  # Assuming UserService exists


@pytest.fixture
def create_users():
    user1 = user_service.create_user(name="User 1")
    user2 = user_service.create_user(name="User 2")
    return [user1, user2]


def test_create_thread(create_users):
    participant_ids = [user["id"] for user in create_users]
    print(f"Participant IDs: {participant_ids}")  # Debugging line
    thread = thread_service.create_thread(participant_ids=participant_ids, meta_data={"topic": "Test Thread"})

    #TODO - Fix participants logic
    #assert thread["participant_ids"] == participant_ids

    assert thread["meta_data"]["topic"] == "Test Thread"
    assert "id" in thread
    assert "created_at" in thread
