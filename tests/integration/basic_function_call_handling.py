"""
Cookbook Demo: Function-Call Round-Trip  (Together AI)
-----------------------------------------------------
• Uses an existing assistant  (ID = "default") that already has the
  `get_flight_times` function-tool attached.
• Sends a user message that should trigger the function.
• Executes the tool server-side and streams the final assistant reply.
"""

import json
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


USER_ID = os.getenv("ENTITIES_USER_ID")  # e.g. user_xxx…
ASSISTANT_ID = "plt_ast_9fnJT01VGrK4a9fcNr8z2O"  # existing assistant
# ASSISTANT_ID = create_assistant.id

MODEL_ID = "together-ai/deepseek-ai/DeepSeek-V3"
PROVIDER_KW = "Hyperbolic"  # router reads model path anyway

# HYPERBOLIC_API_KEY = os.getenv("HYPERBOLIC_API_KEY")    # provider key

HYPERBOLIC_API_KEY = "d2c62c6ff04138210ca7e644fb8270a1d9508fbf93205465958040385a69701b"


# -------------------------------------------
# Temp update tools for master assistant
# --------------------------------------------


update_assistant = client.assistants.update_assistant(
    assistant_id=ASSISTANT_ID,
    tools=[
        {
            "type": "function",
            "function": {
                "name": "get_flight_times",
                "description": "Get flight times",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "departure": {"type": "string"},
                        "arrival": {"type": "string"},
                    },
                    "required": ["departure", "arrival"],
                },
            },
        },
    ],
)
print(f"Updated assistants tools with: {update_assistant.tools} ")


# ------------------------------------------------------------------
# 1.  Tool executor  (runs locally for this demo)
# ------------------------------------------------------------------
def get_flight_times(tool_name: str, arguments) -> str:
    """Fake flight-time lookup with hardened argument handling."""
    if tool_name != "get_flight_times":
        return json.dumps({"status": "error", "message": f"unknown tool '{tool_name}'"})

    # --- DEBUG TRACE ---
    print("[DEBUG] Raw arguments:", repr(arguments), type(arguments))

    # --- NORMALIZATION ---
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as e:
            return json.dumps(
                {
                    "status": "error",
                    "message": "invalid JSON arguments",
                    "detail": str(e),
                    "raw": arguments,
                }
            )

    if not isinstance(arguments, dict):
        return json.dumps(
            {
                "status": "error",
                "message": "arguments must be a dict",
                "received_type": str(type(arguments)),
            }
        )

    # --- SAFE ACCESS ---
    departure = arguments.get("departure")
    arrival = arguments.get("arrival")

    if not departure or not arrival:
        return json.dumps(
            {
                "status": "error",
                "message": "missing required parameters",
                "received": arguments,
            }
        )

    return json.dumps(
        {
            "status": "success",
            "departure": departure,
            "arrival": arrival,
            "duration": "4h 30m",
            "departure_time": "10:00 AM PST",
            "arrival_time": "06:30 PM EST",
        }
    )


# ------------------------------------------------------------------
# 2.  Thread + message + run
# ------------------------------------------------------------------
thread = client.threads.create_thread()

message = client.messages.create_message(
    thread_id=thread.id,
    role="user",
    content="Please fetch me the flight times between LAX and JFK.",
    assistant_id=ASSISTANT_ID,
)

run = client.runs.create_run(assistant_id=ASSISTANT_ID, thread_id=thread.id)

# ------------------------------------------------------------------
# 3.  Stream initial LLM response (should contain the function call)
# ------------------------------------------------------------------
stream = client.synchronous_inference_stream
stream.setup(
    user_id=USER_ID,
    thread_id=thread.id,
    assistant_id=ASSISTANT_ID,
    message_id=message.id,
    run_id=run.id,
    api_key=HYPERBOLIC_API_KEY,
)

print("\n[▶] Initial stream …\n")
for chunk in stream.stream_chunks(
    provider=PROVIDER_KW, model=MODEL_ID, suppress_fc=False, timeout_per_chunk=10.0
):
    if chunk.get("type") == "function_call":
        print(f"\n[function_call] → {chunk['name']}({chunk['arguments']})\n")
    else:
        print(chunk.get("content", ""), end="", flush=True)

# ------------------------------------------------------------------
# 4.  Poll run → execute tool → send tool result
# ------------------------------------------------------------------
handled = client.runs.poll_and_execute_action(
    run_id=run.id,
    thread_id=thread.id,
    assistant_id=ASSISTANT_ID,
    tool_executor=get_flight_times,
    actions_client=client.actions,
    messages_client=client.messages,
    timeout=60.0,
    interval=3,
)

# ------------------------------------------------------------------
# 5.  Stream final assistant response
# ------------------------------------------------------------------
if handled:
    print("\n\n[✓] Tool executed, streaming final answer …\n")

    stream.setup(
        user_id=USER_ID,
        thread_id=thread.id,
        assistant_id=ASSISTANT_ID,
        message_id=message.id,
        run_id=run.id,
        api_key=HYPERBOLIC_API_KEY,
    )

    for chunk in stream.stream_chunks(
        provider=PROVIDER_KW, model=MODEL_ID, timeout_per_chunk=60.0
    ):
        print(chunk.get("content", ""), end="", flush=True)

    print("\n\n--- End of Stream ---")
else:
    print("\n[!] No function call detected or execution failed.")


# post fix example
client = Entity(api_key=os.getenv("ENTITIES_API_KEY"))
thread_id = thread.id
messages = client.messages.list_messages(thread_id=thread_id)

# message_dialogue = client.messages.list_messages(thread_id=thread_id).json()
# print('This is the message dialogue from the orchestrated run:', message_dialogue)

formatted_messages = client.messages.get_formatted_messages(thread_id=thread_id)
print("Formatted inbound messages from the orchestrated run:", formatted_messages)


assistant = client.assistants.retrieve_assistant(assistant_id=ASSISTANT_ID)
print(assistant.tools)
