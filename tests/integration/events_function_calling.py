"""
Debug Mode: Event-Driven Round-Trip (Type Inspection)
---------------------------------------------------
1. Streams high-level Event Instances (ContentEvent, ToolCallRequestEvent, etc.).
2. Prints the Python Class Type and the underlying Payload for every event.
3. Uses event.execute() for the tool execution.
"""

import json
import os

from dotenv import load_dotenv
# Import the new Event classes
from projectdavid import (ComputerExecutionOutputEvent, ContentEvent, Entity,
                          HotCodeEvent, ReasoningEvent, StatusEvent,
                          ToolCallRequestEvent)

# ------------------------------------------------------------------
# 0.  SDK init + env
# ------------------------------------------------------------------
load_dotenv()

# ANSI Colors for Debugging
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
GREY = "\033[90m"
RESET = "\033[0m"

client = Entity(
    base_url=os.getenv("BASE_URL", "http://localhost:9000"),
    api_key=os.getenv("ENTITIES_API_KEY"),
)

# Mandatory for event.execute() to work
if hasattr(client, "synchronous_inference_stream"):
    client.synchronous_inference_stream.bind_clients(
        client.runs, client.actions, client.messages
    )

USER_ID = os.getenv("ENTITIES_USER_ID")
ASSISTANT_ID = "asst_xctd2oI6rHcfqudogaTcdo"
MODEL_ID = "hyperbolic/deepseek-ai/DeepSeek-V3"
PROVIDER_KW = "Hyperbolic"
HYPERBOLIC_API_KEY = os.getenv("HYPERBOLIC_API_KEY")


# ------------------------------------------------------------------
# 1.  Tool executor
# ------------------------------------------------------------------
def get_flight_times(tool_name: str, arguments: dict) -> str:
    """Fake flight-time lookup."""
    return json.dumps(
        {
            "status": "success",
            "departure": arguments.get("departure", "UNK"),
            "arrival": arguments.get("arrival", "UNK"),
            "duration": "4h 30m",
        }
    )


# ------------------------------------------------------------------
# 2.  Setup Thread & Run
# ------------------------------------------------------------------
print(f"{GREY}[1/2] Creating Thread, Message & Run...{RESET}")
thread = client.threads.create_thread()
message = client.messages.create_message(
    thread_id=thread.id,
    role="user",
    content="Please fetch me the flight times between LAX and JFK.",
    assistant_id=ASSISTANT_ID,
)
run = client.runs.create_run(assistant_id=ASSISTANT_ID, thread_id=thread.id)

# ------------------------------------------------------------------
# 3.  Smart Event Stream (DEBUG MODE)
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

print(f"\n{CYAN}[▶] STREAM 1: Event Instance Inspection{RESET}")
print(f"{'EVENT CLASS':<25} | {'TYPED JSON PAYLOAD'}")
print("-" * 100)

tool_event: ToolCallRequestEvent = None

# We iterate over EVENTS
for event in stream.stream_events(provider=PROVIDER_KW, model=MODEL_ID):

    # A. Debug the Type
    class_name = event.__class__.__name__
    payload = event.to_dict()  # This shows the JSON we send to the front-end

    # Pick color based on class
    color = RESET
    if isinstance(event, ContentEvent):
        color = GREEN
    elif isinstance(event, ToolCallRequestEvent):
        color = YELLOW
    elif isinstance(event, ReasoningEvent):
        color = CYAN
    elif isinstance(event, StatusEvent):
        color = GREY

    print(f"{color}{class_name:<25}{RESET} | {json.dumps(payload)}")

    # B. Track if we need to execute a tool
    if isinstance(event, ToolCallRequestEvent):
        tool_event = event

# ------------------------------------------------------------------
# 4.  Execution Round-Trip
# ------------------------------------------------------------------
if tool_event:
    print(f"\n{YELLOW}[LOCAL EXEC] Tool Detected: {tool_event.tool_name}{RESET}")
    success = tool_event.execute(get_flight_times)

    if success:
        print(f"{GREEN}[✓] Tool Executed & Result Submitted.{RESET}")

        print(f"\n{CYAN}[▶] STREAM 2: Final Response Event Inspection{RESET}")
        print(f"{'EVENT CLASS':<25} | {'TYPED JSON PAYLOAD'}")
        print("-" * 100)

        # Re-setup for final answer
        stream.setup(
            user_id=USER_ID,
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
            message_id=message.id,
            run_id=run.id,
            api_key=HYPERBOLIC_API_KEY,
        )

        for event in stream.stream_events(provider=PROVIDER_KW, model=MODEL_ID):
            class_name = event.__class__.__name__
            payload = event.to_dict()
            color = GREEN if isinstance(event, ContentEvent) else GREY
            print(f"{color}{class_name:<25}{RESET} | {json.dumps(payload)}")

    else:
        print(f"{RED}[!] Tool execution submission failed.{RESET}")
else:
    print(f"\n{RED}[!] No ToolCallRequestEvent found in stream.{RESET}")

print(f"\n{GREY}--- End of Debug Script ---{RESET}")
