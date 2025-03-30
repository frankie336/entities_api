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

### 🔧 Step 2: Install the SDK

git clone https://github.com/frankie336/entities_api
 
cd entities_api   
python start.py


🤖 **Building Your SQL-Ready Assistant (Code Example)**

```python

import json
import logging
import threading
from entities import Entities

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inference")

client = Entities()

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



#-----------------------------------------------------------
# You only need to  complete the above steps  once per  
# function call. 
#  
#-----------------------------------------------------------
            

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

# Function Call handler Class
class FunctionCallService:
    def __init__(self):
        self.function_handlers = {
            "movie_database": self.handle_get_movie_database
        }

    def call_function(self, function_name, arguments):
        return self.function_handlers[function_name](arguments)

    @staticmethod
    def handle_get_movie_database(arguments):
        """
        Replace this with your actual SQL adapter logic.
        """
        parsed_args = json.loads(arguments) if isinstance(arguments, str) else arguments
        query = parsed_args.get("query")
        logger.info(f"Executing SQL: {query}")
        # Simulate response
        return {"rows": [{"title": "Oblivion", "year": 2013, "rating": 7.1}]}

# Threaded SSE Monitoring
def monitor_run():
    def my_callback(event_type: str, event_data: dict):
        logger.info(f"🔔 Event received: {event_type}")
        if event_type == 'tool_invoked':
            tool_name = event_data.get("tool_name")
            arguments = event_data.get("function_args")
            tool_call_id = event_data.get("tool_call_id")
            tool_id = event_data.get("tool_id")
            thread_id = event_data.get("thread_id")
            assistant_id = event_data.get("assistant_id")

            handler = FunctionCallService()
            result = handler.call_function(tool_name, arguments)

            client.message_service.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_id=tool_id,
                role="tool",
                content=json.dumps(result)
            )
            
            client.actions.update_action(
                action_id=tool_call_id,
                status="completed"
            )
            
            #-----------------------------------------------------------
            # You have now completed the function call life cycle 
            # The assistant will now synthesize its response 
            # with content from your database. 
            #-----------------------------------------------------------
            
            logger.info("✅ Tool output submitted and action marked complete.")

    threading.Thread(
        target=lambda: client.runs_monitor.start(run.id, callback=my_callback),
        daemon=True
    ).start()

# Start monitoring
monitor_run()

# Start streaming response
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


            