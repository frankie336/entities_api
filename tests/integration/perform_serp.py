import os

from dotenv import load_dotenv
from projectdavid import Entity

# ------------------------------------------------------------------
# 0.  SDK init + env
# ------------------------------------------------------------------
load_dotenv()

client = Entity(
    base_url=os.getenv("BASE_URL", "http://localhost:9000"),
    api_key=os.getenv("ADMIN_API_KEY"),
)

search = client.tools.web_serp(
    query="Find the 2024 revenue of NVIDIA ",
)

print(search)
