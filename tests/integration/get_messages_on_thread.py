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


# ----------------------------------------------------------
# Below shows thread activity on the research workers thread
# -----------------------------------------------------------
thread = "thread_pSIeGIBnBOmVihQwnCDhKe"
messages_on_thread = client.messages.get_formatted_messages(thread_id=thread)
if len(messages_on_thread) > 0:
    print(messages_on_thread[0:5])  # Prints the last message
else:
    print("No messages found in the thread.")


thread = "thread_wfUv7UWTHVQD1Oraz9Ejqf"

messages_on_thread = client.messages.get_formatted_messages(thread_id=thread)
if len(messages_on_thread) > 0:
    print(messages_on_thread[-1].values())  # Prints the last message
else:
    print("No messages found in the thread.")
