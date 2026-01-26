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
get_assistant = client.assistants.retrieve_assistant(assistant_id=ASSISTANT_ID)
print(get_assistant.tools)
