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

# worker_thread_1 = "thread_ME1N5l5NSXTzLdbOjlxPXt"
# worker_thread_2 = "thread_qcsPmVNgJbPJGOgxZ3WtuE"
# worker_thread_3 = "thread_QEkizVy7EPP0mAaSHhyzkU"
# worker_thread_4 = "thread_FOEG0qcHgSgaOGblRsS3zw"
# worker_thread_5 = "thread_iu0vsqermruGKGQdCr5pNR"


worker_thread_1 = "thread_CYJPc0yOxb9YjZfVBhvDmF"
worker_thread_2 = "thread_V9umJGVqnvuMlkPhCDxEgI"
worker_thread_3 = "thread_QEkizVy7EPP0mAaSHhyzkU"
worker_thread_4 = "thread_FOEG0qcHgSgaOGblRsS3zw"
worker_thread_5 = "thread_iu0vsqermruGKGQdCr5pNR"


messages_on_thread = client.messages.get_formatted_messages(thread_id=worker_thread_1)

print(messages_on_thread)
print(len(messages_on_thread))

"""
1. worker is not synthesising content

"""
