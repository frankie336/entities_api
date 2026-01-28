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

run = "run_PjjnC8veAIN7elg8MItg2u"

pending_action = client.actions.get_pending_actions(run)
print(pending_action)
