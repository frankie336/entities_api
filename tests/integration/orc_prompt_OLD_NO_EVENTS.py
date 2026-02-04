"""
Standard Inference Test (No Tools)
---------------------------------------------------
1. Simple prompt -> response.
2. Handles Reasoning (DeepSeek) and Content events.
3. No tool execution or recursion logic.
"""

import os

from dotenv import load_dotenv
from projectdavid import Entity

load_dotenv()

# --------------------------------------------------
# Load the Entities client with your user API key
# Note: if you define ENTITIES_API_KEY="ea_6zZiZ..."
# in .env, you do not need to pass in the API key directly.
# We pass in here directly for clarity
# ---------------------------------------------------
client = Entity(base_url="http://localhost:9000", api_key=os.getenv("ENTITIES_API_KEY"))

user_id = os.getenv("ENTITIES_USER_ID")

# -----------------------------
# create an assistant
# ------------------------------
assistant = client.assistants.create_assistant(
    name="test_assistant",
    instructions="You are a helpful AI assistant",
)
print(f"created assistant with ID: {assistant.id}")

# -----------------------------------------------
# Create a thread
# Note:
# - Threads are re-usable
# Reuse threads in the case you want as continued
# multi turn conversation
# ------------------------------------------------
print("Creating thread...")
thread = client.threads.create_thread()

print(f"created thread with ID: {thread.id}")
# Store the dynamically created thread ID
actual_thread_id = thread.id


# -----------------------------------------
#  Create a message using the NEW thread ID
# --------------------------------------------
print(f"Creating message in thread {actual_thread_id}...")
message = client.messages.create_message(
    thread_id=actual_thread_id,
    role="user",
    content="Hello, assistant! Tell me about the latest trends in AI.",
    assistant_id=assistant.id,
)
print(f"Created message with ID: {message.id}")

# ---------------------------------------------
# step 3 - Create a run using the NEW thread ID
# ----------------------------------------------
print(f"Creating run in thread {actual_thread_id}...")
run = client.runs.create_run(assistant_id=assistant.id, thread_id=actual_thread_id)
print(f"Created run with ID: {run.id}")

# ------------------------------------------------
# Instantiate the synchronous streaming helper
# --------------------------------------------------
sync_stream = client.synchronous_inference_stream

# ------------------------------------------------------
# step 4 - Set up the stream using the NEW thread ID
# --------------------------------------------------------
print(f"Setting up stream for thread {actual_thread_id}...")
sync_stream.setup(
    user_id=user_id,
    thread_id=actual_thread_id,
    assistant_id=assistant.id,
    message_id=message.id,
    run_id=run.id,
    api_key=os.getenv("HYPERBOLIC_API_KEY"),
)
print("Stream setup complete. Starting streaming...")

# --- Stream initial LLM response ---
try:
    for chunk in sync_stream.stream_chunks(
        provider="Hyperbolic",
        model="hyperbolic/deepseek-ai/DeepSeek-V3-0324",  # Ensure this model is valid/available
        timeout_per_chunk=15.0,
    ):
        content = chunk.get("content", "")
        if content:
            print(content, end="", flush=True)
    print("\n--- End of Stream ---")  # Add newline after stream
except Exception as e:
    print(f"\n--- Stream Error: {e} ---")  # Catch errors during streaming

print("Script finished.")
