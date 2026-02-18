import os

from config_orc_fc import config
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

assistant = client.assistants.update_assistant(
    assistant_id=config.get("assistant_id"),
)


print(f"Agent Mode:{assistant.agent_mode}")
print(f"Telemetry: {assistant.decision_telemetry}")
print(f"Web access:{assistant.web_access}")
print(f"Deep Research:{assistant.deep_research}")
print(assistant.id)
