import json
import os
import re
import sys

import dotenv
import requests

dotenv.load_dotenv()

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------
HYPERBOLIC_API_KEY = os.getenv("HYPERBOLIC_API_KEY")
if not HYPERBOLIC_API_KEY:
    HYPERBOLIC_API_KEY = "PASTE_KEY_HERE"

URL = "https://api.hyperbolic.xyz/v1/chat/completions"
MODEL = "meta-llama/Meta-Llama-3.1-405B-Instruct"

TEST_PROMPT = "Please fetch me the flight times between LAX and JFK. Use the get_flight_times tool."

# ------------------------------------------------------------------
# 1. Manual Tool Definition & System Prompt
# ------------------------------------------------------------------

TOOLS_DEFINITION = [
    {
        "name": "get_flight_times",
        "description": "Return flight times between two airport codes.",
        "parameters": {
            "departure": "3-letter airport code (e.g. LAX)",
            "arrival": "3-letter airport code (e.g. JFK)",
        },
    }
]

SYSTEM_PROMPT_TEXT = f"""You are a helpful assistant with access to the following tools:

{json.dumps(TOOLS_DEFINITION, indent=2)}

### INSTRUCTIONS:
1. To use a tool, output ONLY the JSON object wrapped in <tool_code> tags.
2. Format: <tool_code>{{"name": "tool_name", "arguments": {{...}} }}</tool_code>
3. DO NOT include semicolons or extra text inside the tags.
4. Wait for the user to provide the [Tool Output].
5. Once you receive the [Tool Output], verify the data and provide your final natural language answer.
"""


def execute_local_tool(tool_name: str, arguments: dict) -> str:
    print(f"\n[LOCAL EXECUTION] Running '{tool_name}' with args: {arguments}")
    if tool_name == "get_flight_times":
        return json.dumps(
            {
                "status": "success",
                "flights": [
                    {
                        "flight": "UA123",
                        "departs": "10:00 AM PST",
                        "arrives": "06:00 PM EST",
                    },
                    {
                        "flight": "AA456",
                        "departs": "02:00 PM PST",
                        "arrives": "10:30 PM EST",
                    },
                ],
            }
        )
    return json.dumps({"error": "Tool not found"})


# ------------------------------------------------------------------
# 2. Stream Handler
# ------------------------------------------------------------------


def run_turn(messages):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {HYPERBOLIC_API_KEY}",
    }

    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.1,
        "stream": True,
        "stop": ["</tool_code>"],  # Prevents model from yapping after the tag
    }

    print(f"\n--- STARTING STREAM TURN (Msgs: {len(messages)}) ---")

    full_content = ""
    buffer = ""
    is_tool_call = False

    try:
        with requests.post(URL, headers=headers, json=payload, stream=True) as response:
            if response.status_code != 200:
                print(f"[API ERROR {response.status_code}]: {response.text}")
                return None, []

            for line in response.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data: "):
                    continue

                data_str = decoded[6:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                    if "choices" in chunk and len(chunk["choices"]) > 0:
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")

                        if content:
                            full_content += content
                            buffer += content

                            if "<tool_code>" in buffer:
                                is_tool_call = True

                            if not is_tool_call:
                                sys.stdout.write(content)
                                sys.stdout.flush()
                except:
                    pass
    except Exception as e:
        print(f"\n[CONNECTION ERROR] {e}")
        return None, []

    # If the stream was cut off by the 'stop' sequence, manually re-add the closing tag
    # so the regex logic below finds it.
    if is_tool_call and "</tool_code>" not in full_content:
        full_content += "</tool_code>"

    print("\n[STREAM COMPLETE]")

    # --- ROBUST TOOL PARSING ---
    extracted_tools = []
    tool_pattern = r"<tool_code>(.*?)</tool_code>"
    matches = re.findall(tool_pattern, full_content, re.DOTALL)

    for match in matches:
        # Clean trailing semicolons and whitespace
        clean_json_str = match.strip().rstrip(";")

        try:
            call_data = json.loads(clean_json_str)
            extracted_tools.append(call_data)
        except json.JSONDecodeError:
            # Safety fallback: find the last closing brace
            try:
                end_index = clean_json_str.rfind("}")
                if end_index != -1:
                    call_data = json.loads(clean_json_str[: end_index + 1])
                    extracted_tools.append(call_data)
                else:
                    print(f"[PARSE ERROR] No valid JSON object found in: {match}")
            except Exception as e:
                print(f"[PARSE ERROR] Could not parse tool JSON: {match} | {e}")

    return full_content, extracted_tools


# ------------------------------------------------------------------
# 3. Main Logic
# ------------------------------------------------------------------

if __name__ == "__main__":
    conversation_history = [
        {"role": "system", "content": SYSTEM_PROMPT_TEXT},
        {"role": "user", "content": TEST_PROMPT},
    ]

    # --- TURN 1 (Assistant generates tool call) ---
    assistant_text, tool_calls = run_turn(conversation_history)

    if not assistant_text:
        print("No response.")
        sys.exit(1)

    conversation_history.append({"role": "assistant", "content": assistant_text})

    if tool_calls:
        print(f"\n[SYSTEM] Detected {len(tool_calls)} manual tool calls.")

        for tc in tool_calls:
            func_name = tc.get("name")
            args = tc.get("arguments")

            result_str = execute_local_tool(func_name, args)
            tool_feedback = f"[Tool Output for {func_name}]: {result_str}"

            conversation_history.append({"role": "user", "content": tool_feedback})

        # --- TURN 2 (Assistant processes results) ---
        print("\n[SYSTEM] Sending results back to model...")
        final_answer, _ = run_turn(conversation_history)

        if final_answer:
            print(f"\n\n[FINAL RESULT]\n{final_answer}")
    else:
        print("\n[SYSTEM] No tools triggered.")
