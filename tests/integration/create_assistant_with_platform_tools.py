""" """

import os

from dotenv import load_dotenv
from projectdavid import Entity

from src.api.entities_api.platform_tools.definitions.code_interpreter import (
    code_interpreter,
)
from src.api.entities_api.platform_tools.definitions.computer import computer
from src.api.entities_api.platform_tools.definitions.file_search import file_search
from src.api.entities_api.platform_tools.definitions.web_search import web_search

# ------------------------------------------------------------------
# 0.  SDK init + env
# ------------------------------------------------------------------
load_dotenv()

client = Entity(
    base_url=os.getenv("BASE_URL", "http://localhost:9000"),
    api_key=os.getenv("ENTITIES_API_KEY"),
)


# -------------------------------------------
# create_assistant
# --------------------------------------------

assistant = client.assistants.create_assistant(
    name="Test Assistant",
    model="gpt-oss-120b",
    instructions="You are a helpful AI assistant, your name is Nexa.",
    tools=[
        {"type": "code_interpreter"},
        {"type": "computer"},
        {"type": "file_search"},
        {
            "type": "function",
            "function": {
                "name": "get_flight_times",
                "description": "Get flight times",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "departure": {"type": "string"},
                        "arrival": {"type": "string"},
                    },
                    "required": ["departure", "arrival"],
                },
            },
        },
    ],
)

print(assistant.id)
print(assistant.tools)
