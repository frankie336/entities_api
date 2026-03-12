# tests/integration/vector_store_pipeline.py
import json
import os

from config_orc_fc import config
from dotenv import load_dotenv
from projectdavid import Entity

load_dotenv()


client = Entity(
    base_url=os.getenv("BASE_URL", "http://localhost:9000"),
    api_key=os.getenv("ENTITIES_API_KEY"),  # This is the entities user API Key
)

# --------------------------
# 1. Create a vector store
# ---------------------------
print("--- Creating Vector Store ---")
vector_store = client.vectors.create_vector_store(name="Test Vector Store 1")
print(f"Created: {vector_store.id}\n")

# ---------------------------------
# 2. Upload file to vector store
# ----------------------------------
print("--- Uploading File ---")
save_file_to_store = client.vectors.add_file_to_vector_store(
    vector_store_id=vector_store.id,
    file_path="People_on_war _241118_200546.pdf",
)
print(f"File Uploaded: {save_file_to_store.file_name}\n")

# ---------------------------
# 3. List files in store
# ---------------------------
list_files_in_store = client.vectors.list_store_files(vector_store_id=vector_store.id)
print("--- Files in Store ---")
print(list_files_in_store)
print("\n")

# --------------------------------------
# 4. Attach to Assistant (and enable tool!)
# ----------------------------------------
print("--- Updating Assistant ---")
update_assistant = client.assistants.update_assistant(
    assistant_id=config.get("assistant_id"),
    tools=[{"type": "file_search"}],  # 👈 CRITICAL: Tells the LLM the tool exists!
    tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}},
)

print(f"Assistant Tools: {update_assistant.tools}")
print(f"Assistant Resources: {update_assistant.tool_resources}\n")


# --------------------------------------
# 5. Direct Test Query (The Beautiful Envelope)
# --------------------------------------
print("--- Running Direct Vector Search (Envelope) ---")
query = "What percentage of Palestinians reported being tortured?"

try:
    print(f"Executing simple envelope search for: '{query}'...\n")

    # Grab the envelope via SDK
    envelope_results = client.vectors.vector_file_search_raw(
        vector_store_id=vector_store.id, query_text=query, top_k=3
    )

    # Pretty print the envelope
    print("✨ Beautiful Envelope Results:")
    print(json.dumps(envelope_results, indent=2))

except Exception as e:
    print(f"❌ Envelope search failed: {e}")
