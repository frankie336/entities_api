import os

from dotenv import load_dotenv
from projectdavid import Entity

load_dotenv()

from config_orc_fc import config

client = Entity(
    base_url=os.getenv("BASE_URL", "http://localhost:9000"),
    api_key=os.getenv("ENTITIES_API_KEY"),  # This is the entities user API Key
)


# --------------------------
# create a vector store
# ---------------------------
vector_store = client.vectors.create_vector_store(name="Test Vector Store1")
print(vector_store)
# ---------------------------------
# Upload file to vector store
# ----------------------------------
save_file_to_store = client.vectors.add_file_to_vector_store(
    vector_store_id=vector_store.id,
    file_path="People_on_war _241118_200546.pdf",
)
# ---------------------------
# list files in store
# ---------------------------
list_files_in_store = client.vectors.list_store_files(vector_store_id=vector_store.id)
print(list_files_in_store)

# --------------------------------------
# To make the files accessible to your assistant, update the assistant’s tool_resources with the new vector_store id.
# ----------------------------------------


update_assistant = client.assistants.update_assistant(
    assistant_id=config.get("assistant_id"),
    tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}},
)

print(update_assistant.tool_resources)

# {'file_search': {'vector_store_ids': ['vect_WgPq4s8ioqHHPxwOgDIRys']}}
