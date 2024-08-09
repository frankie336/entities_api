from starlette.testclient import TestClient
from api.app import create_test_app

app = create_test_app()
client = TestClient(app)

def test_create_message():
    # Test data for users
    user1_response = client.post("/v1/users", json={"name": "User 1"})
    user2_response = client.post("/v1/users", json={"name": "User 2"})

    assert user1_response.status_code == 200
    assert user2_response.status_code == 200

    user1 = user1_response.json()
    user2 = user2_response.json()

    # Test data for thread
    thread_data = {
        "participant_ids": [user1['id'], user2['id']]
    }

    # Create thread
    thread_response = client.post("/v1/threads", json=thread_data)
    assert thread_response.status_code == 200

    thread = thread_response.json()
    assert thread["object"] == "thread"

    # Test data for message
    message_data = {
        "content": [{
            "text": {
                "annotations": [],
                "value": "I need to solve the equation `3x + 11 = 14`. Can you help me?"
            },
            "type": "text"
        }],
        "role": "user",
        "thread_id": thread['id'],
        "sender_id": user1['id'],
        "meta_data": {}
    }

    # Create message
    message_response = client.post("/v1/messages", json=message_data)
    assert message_response.status_code == 200

def test_create_message_invalid_thread():
    # Test data for user
    user_response = client.post("/v1/users", json={"name": "User 1"})
    assert user_response.status_code == 200

    user = user_response.json()

    # Test data for message with invalid thread ID
    message_data = {
        "content": [{
            "text": {
                "annotations": [],
                "value": "This is a test message"
            },
            "type": "text"
        }],
        "role": "user",
        "thread_id": "invalid_thread_id",
        "sender_id": user['id'],
        "meta_data": {}
    }

    # Create message
    message_response = client.post("/v1/messages", json=message_data)
    assert message_response.status_code == 404
    assert message_response.json()["detail"] == "Thread not found"

def test_create_message_invalid_user():
    # Test data for thread
    thread_response = client.post("/v1/threads", json={"participant_ids": []})
    assert thread_response.status_code == 200

    thread = thread_response.json()

    # Test data for message with invalid user ID
    message_data = {
        "content": [{
            "text": {
                "annotations": [],
                "value": "This is a test message"
            },
            "type": "text"
        }],
        "role": "user",
        "thread_id": thread['id'],
        "sender_id": "invalid_user_id",
        "meta_data": {}
    }

    # Create message
    message_response = client.post("/v1/messages", json=message_data)
    assert message_response.status_code == 404
    assert message_response.json()["detail"] == "Sender not found"  # Update expected error message
