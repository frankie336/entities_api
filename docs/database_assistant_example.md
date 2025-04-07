## ✅ How to Use Function Calling with a Movie Database using Entities V1

Hello Martin — thanks for the kind words, they mean a lot.

Just to clarify: **LLaMA 2 was not specifically trained for OpenAI-style function calling**, and because of this (and a few other reasons), I highly recommend upgrading to one of the newer state-of-the-art models.

If you're committed to Meta models, then your best choice is **LLaMA 3.3**, which is fully supported in **Entities V1** for function calling.

Assuming you're happy to migrate, here's a clean walkthrough on how to implement your movie-database assistant using our stack.

---

### 🔧 Step 1: Install the SDK

> This gives you Python access to the full Entities API.

```bash
pip install git+https://github.com/frankie336/entitites_sdk.git
```

### 🔧 Step 2: Install the API Server

```bash
git clone https://github.com/frankie336/entities_api
cd entities_api   
python start.py
```

---

## 🤖 **Building Your SQL-Ready Assistant (Code Example)**

```python
import json
import logging
from entities_api import Entities
from entities_api import EventsInterface
from entities_api.clients.actions import ActionsClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inference")

client = Entities()
actions_client = ActionsClient()

# Step 1: Create a user
user = client.users.create_user(name="user_name_here")

# Step 2: Create an assistant
assistant = client.assistants.create_assistant(
    name="Database Agent",
    instructions="You are a helpful AI assistant, connected to a movie database."
)

# Step 3: Register the SQL query tool
func_def = {
    "type": "function",
    "function": {
        "name": "movie_database",
        "description": (
            "Executes a read-only SQL query on the movie database. "
            "Use this to look up movies by title, actor, genre, director, release year, or rating."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query. Example: SELECT * FROM movies WHERE genre = 'horror';"
                }
            },
            "required": ["query"]
        }
    }
}

tool = client.tools.create_tool(
    name="sql_query_tool",
    type="function",
    function=func_def,
    assistant_id=assistant.id
)

client.tools.associate_tool_with_assistant(
    tool_id=tool.id,
    assistant_id=assistant.id
)

# Step 4: Start a conversation
thread = client.threads.create_thread(participant_ids=user.id)

message = client.messages.create_message(
    thread_id=thread.id,
    assistant_id=assistant.id,
    content="Can you show me all horror movies starring Tom Cruise released after 2010 with an IMDb rating above 6?",
    role="user"
)

# Step 5: Create a run
run = client.runs.create_run(
    thread_id=thread.id,
    assistant_id=assistant.id
)


# ------------------------------
# Function Call handler Class
# Can be scaled to handle and manage additional calls 
# ------------------------------

class FunctionCallService:
    def __init__(self):
        self.function_handlers = {
            "movie_database": self.handle_get_movie_database
        }

    def call_function(self, function_name, arguments):
        return self.function_handlers[function_name](arguments)

    @staticmethod
    def handle_get_movie_database(arguments):
        parsed_args = json.loads(arguments) if isinstance(arguments, str) else arguments
        query = parsed_args.get("query")
        logger.info(f"Executing SQL: {query}")
        return {"rows": [{"title": "Oblivion", "year": 2013, "rating": 7.1}]}


# ------------------------------
# ✅ NEW: Asynchronous Monitor using MonitorLauncher
# ------------------------------

def my_custom_tool_handler(run_id, run_data, pending_actions):
    logger.info(f"[ACTION_REQUIRED] run {run_id} has {len(pending_actions)} pending action(s)")
    for action in pending_actions:
        action_id = action.get("id")
        tool_name = action.get("tool_name")
        args = action.get("function_args")

        logger.info(f"[ACTION] Tool: {tool_name}, Args: {args}")

        handler = FunctionCallService()
        result = handler.call_function(tool_name, args)

        client.message_service.submit_tool_output(
            thread_id=run_data["thread_id"],
            assistant_id=run_data["assistant_id"],
            tool_id=action.get("tool_id"),
            role="tool",
            content=json.dumps(result)
        )

        client.actions.update_action(
            action_id=action_id,
            status="completed"
        )

        logger.info("✅ Tool output submitted and action marked complete.")


# 🔄 Launch the monitor in the background
monitor = EventsInterface.MonitorLauncher(
    client=client,
    actions_client=actions_client,
    run_id=run.id,
    on_action_required=my_custom_tool_handler,
    events=EventsInterface
)
monitor.start()

# ------------------------------
# Step 6: Stream the assistant response
# ------------------------------
stream = client.synchronous_inference_stream
stream.setup(
    user_id=user.id,
    thread_id=thread.id,
    assistant_id=assistant.id,
    message_id=message.id,
    run_id=run.id
)

try:
    print("📡 Streaming assistant response...\n")
    for chunk in stream.stream_chunks(provider="Hyperbolic", model="meta-llama/Llama-3.3-70B-Instruct"):
        print(json.dumps(chunk))
    print("\n✅ Stream complete.")
except Exception as e:
    logger.error("❌ Stream failed: %s", str(e))
finally:
    try:
        stream.close()
    except Exception as e:
        logger.warning("⚠️ Stream cleanup failed: %s", str(e))
```

---

## ✅ Summary

- The assistant now handles `function_call` events via the `MonitorLauncher`, which runs in a non-blocking background thread.
- When the assistant reaches `requires_action`, your handler receives the full `action_id`, `tool_name`, and `function_args`.
- You can scale this pattern across multiple assistants and tools with pluggable handler logic.

Ready to expand this to support retries, fallback tools, or multiple models? Just say the word.
