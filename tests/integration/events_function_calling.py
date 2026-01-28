"""
Debug Mode: Function-Call Round-Trip (Smart Events)
---------------------------------------------------
1. Streams high-level Events (Content vs ToolRequest).
2. SDK handles buffering, JSON parsing, and argument unwrapping.
3. Consumer calls event.execute() directly.
4. Streams final response.
"""

import json
import os

from dotenv import load_dotenv

# Import the new Event classes to use in isinstance checks
from projectdavid import ContentEvent, Entity, StatusEvent, ToolCallRequestEvent

# ------------------------------------------------------------------
# 0.  SDK init + env
# ------------------------------------------------------------------
load_dotenv()

# ANSI Colors
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

USER_ID = os.getenv("ENTITIES_USER_ID")
ASSISTANT_ID = "asst_bToQ4dQQnuhJuhlU5M6COG"
MODEL_ID = "hyperbolic/deepseek-ai/DeepSeek-V3"
PROVIDER_KW = "Hyperbolic"
HYPERBOLIC_API_KEY = os.getenv("HYPERBOLIC_API_KEY")


# ------------------------------------------------------------------
# 1.  Tool executor
# ------------------------------------------------------------------
def get_flight_times(tool_name: str, arguments: dict) -> str:
    """Fake flight-time lookup."""
    print(
        f"\n{YELLOW}[LOCAL EXEC] Tool invoked: {tool_name} | Args: {arguments}{RESET}"
    )
    return json.dumps(
        {
            "status": "success",
            "departure": arguments.get("departure", "UNK"),
            "arrival": arguments.get("arrival", "UNK"),
            "duration": "4h 30m",
            "departure_time": "10:00 AM PST",
            "arrival_time": "06:30 PM EST",
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
# 3.  Smart Event Stream
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

print(f"\n{CYAN}[▶] STREAM 1: Thinking & Tool Detection{RESET}")

tool_was_executed = False

# We iterate over EVENTS, not raw chunks
for event in stream.stream_events(provider=PROVIDER_KW, model=MODEL_ID):

    # A. Handle Standard Text
    if isinstance(event, ContentEvent):
        print(f"{GREEN}{event.content}{RESET}", end="", flush=True)

    # B. Handle Tool Requests (SDK has already buffered & parsed args)
    elif isinstance(event, ToolCallRequestEvent):
        print(f"\n\n{CYAN}[SDK] Tool Request Detected: '{event.tool_name}'{RESET}")
        print(f"{CYAN}      Arguments: {event.args}{RESET}")

        # Execute immediately using the Event's helper
        success = event.execute(get_flight_times)

        if success:
            print(f"{GREEN}[✓] Tool Executed & Output Submitted.{RESET}")
            tool_was_executed = True
        else:
            print(f"{RED}[!] Tool Execution Failed.{RESET}")

    # C. Handle Status Changes (Optional logging)
    elif isinstance(event, StatusEvent):
        # Just distinct logging for stream completion
        if event.status == "complete":
            print(f"\n{GREY}--- Turn Complete ---{RESET}")

# ------------------------------------------------------------------
# 4.  Final Response (Stream 2)
# ------------------------------------------------------------------
if tool_was_executed:
    print(f"\n{CYAN}[▶] STREAM 2: Final Response{RESET}")

    # Re-setup for the answer generation
    stream.setup(
        user_id=USER_ID,
        thread_id=thread.id,
        assistant_id=ASSISTANT_ID,
        message_id=message.id,
        run_id=run.id,
        api_key=HYPERBOLIC_API_KEY,
    )

    for event in stream.stream_events(provider=PROVIDER_KW, model=MODEL_ID):
        if isinstance(event, ContentEvent):
            print(f"{GREEN}{event.content}{RESET}", end="", flush=True)

    print(f"\n{GREY}--- End of Script ---{RESET}")

else:
    print(f"\n{RED}[!] No tool call occurred.{RESET}")
