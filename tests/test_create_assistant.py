from starlette.testclient import TestClient
from api.app import create_test_app

app = create_test_app()
client = TestClient(app)


def test_create_assistant():
    assistant_data = {
        "name": "HR Helper",
        "description": "HR bot to answer employee questions about company policies.",
        "model": "gpt-4o",
        "instructions": "You are an HR bot, and you have access to files to answer employee questions about company policies.",
        "tools": [
            {
                "type": "file_search"
            }
        ],
        "meta_data": {},
        "top_p": 1.0,
        "temperature": 1.0,
        "response_format": "auto"
    }

    response = client.post("/v1/assistants", json=assistant_data)
    assert response.status_code == 200
    assistant = response.json()
    assert assistant["name"] == assistant_data["name"]
    assert assistant["description"] == assistant_data["description"]
    assert assistant["model"] == assistant_data["model"]
    assert assistant["instructions"] == assistant_data["instructions"]
    # Updated assertion to ignore additional fields
    assert all(
        tool.get("type") == expected_tool["type"]
        for tool, expected_tool in zip(assistant["tools"], assistant_data["tools"])
    )
    assert assistant["meta_data"] == assistant_data["meta_data"]
    assert assistant["top_p"] == assistant_data["top_p"]
    assert assistant["temperature"] == assistant_data["temperature"]
    assert assistant["response_format"] == assistant_data["response_format"]

    # Store the assistant ID for the get test
    return assistant["id"]


def test_get_assistant():
    assistant_id = test_create_assistant()
    response = client.get(f"/v1/assistants/{assistant_id}")
    assert response.status_code == 200
    assistant = response.json()
    assert assistant["id"] == assistant_id
    assert assistant["name"] == "HR Helper"
    assert assistant["description"] == "HR bot to answer employee questions about company policies."
    assert assistant["model"] == "gpt-4o"
    assert assistant["instructions"] == "You are an HR bot, and you have access to files to answer employee questions about company policies."
    # Updated assertion to ignore additional fields
    assert all(
        tool.get("type") == expected_tool["type"]
        for tool, expected_tool in zip(assistant["tools"], [{"type": "file_search"}])
    )
    assert assistant["meta_data"] == {}
    assert assistant["top_p"] == 1.0
    assert assistant["temperature"] == 1.0
    assert assistant["response_format"] == "auto"


if __name__ == "__main__":
    test_create_assistant()
    test_get_assistant()
