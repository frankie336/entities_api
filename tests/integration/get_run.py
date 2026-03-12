import os

from dotenv import load_dotenv
from projectdavid import Entity

# ------------------------------------------------------------------
# 0.  SDK init + env
# ------------------------------------------------------------------
load_dotenv()

client = Entity(
    base_url=os.getenv("BASE_URL", "http://localhost:9000"),
    api_key=os.getenv("INTRUDER_API_KEY"),
)


get_run = client.runs.retrieve_run(run_id="run_m7RlewfE0MYRJHL0ZYPKr1")
print(get_run.thread_id)
print(get_run)

update_run = client.runs.update_run_fields(
    run_id="run_m7RlewfE0MYRJHL0ZYPKr1", meta_data={"api_key": "test_api_key"}
)

run = client.runs.retrieve_run(run_id="run_m7RlewfE0MYRJHL0ZYPKr1")
print(run.meta_data.get("api_key"))
