""" """

import os

from dotenv import load_dotenv
from projectdavid import Entity

# ------------------------------------------------------------------
# 0.  SDK init + env
# ------------------------------------------------------------------
load_dotenv()

client = Entity(
    base_url=os.getenv("BASE_URL", "http://localhost:9000"),
    api_key=os.getenv("ENTITIES_API_KEY"),
)

ASSISTANT_ID = "plt_ast_9fnJT01VGrK4a9fcNr8z2O"

# -------------------------------------------
# Update an assistants tools
# --------------------------------------------
update_assistant = client.assistants.update_assistant(
    assistant_id=ASSISTANT_ID,
    tools=[
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
print(f"Updated assistants tools with: {update_assistant.tools} ")
