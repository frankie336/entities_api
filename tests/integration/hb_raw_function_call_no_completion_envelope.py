import json
import os
import sys

import requests
from dotenv import load_dotenv

# ------------------------------------------------------------------
# CONFIG LOAD
# ------------------------------------------------------------------

load_dotenv()

CONFIG_FILE = "hb_raw_function_call_no_completions_config.json"
config = {}

try:
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"[WARN] {CONFIG_FILE} not found — using env/defaults")
except json.JSONDecodeError:
    print(f"[ERROR] {CONFIG_FILE} invalid JSON")
    sys.exit(1)

API_KEY = (
    os.getenv("HYPERBOLIC_API_KEY")
    or config.get("hyperbolic_api_key")
    or os.getenv("TOGETHER_API_KEY")
)

if not API_KEY:
    print("[FATAL] Missing API key")
    sys.exit(1)

URL = config.get(
    "url",
    # try raw-style endpoint first
    "https://api.hyperbolic.xyz/v1/completions",
)

MODEL = config.get("model", "openai/gpt-oss-120b")

TEST_PROMPT = config.get(
    "test_prompt", "You may call tools. Flight times between LAX and JFK?"
)

print(f"[CONFIG] URL: {URL}")
print(f"[CONFIG] MODEL: {MODEL}")

# ------------------------------------------------------------------
# PROMPT BUILDER — FLATTEN CHAT → RAW PROMPT
# ------------------------------------------------------------------


def flatten_messages(messages):
    """
    Converts chat messages into a raw prompt string.
    Preserves roles for model conditioning.
    """
    parts = []
    for m in messages:
        role = m["role"].upper()
        parts.append(f"{role}: {m['content']}")
    parts.append("ASSISTANT:")
    return "\n".join(parts)


# ------------------------------------------------------------------
# RAW STREAM RUNNER
# ------------------------------------------------------------------


def run_raw_turn(messages):

    prompt = flatten_messages(messages)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "max_tokens": 512,
        "temperature": 0.3,
        "stream": True,
    }

    print("\n=== RAW PROMPT SENT ===")
    print(prompt)
    print("=======================\n")

    full_text = ""

    with requests.post(URL, headers=headers, json=payload, stream=True) as r:

        if r.status_code != 200:
            print("[HTTP ERROR]", r.status_code)
            print(r.text)
            r.raise_for_status()

        for line in r.iter_lines():
            if not line:
                continue

            decoded = line.decode()

            # Hyperbolic-compatible SSE
            if decoded.startswith("data:"):
                decoded = decoded[5:].strip()

            if decoded == "[DONE]":
                print("\n[STREAM DONE]")
                break

            try:
                chunk = json.loads(decoded)
            except json.JSONDecodeError:
                print("[NON JSON CHUNK]", decoded)
                continue

            # ---- RAW COMPLETION FORMAT ----
            # usually: choices[0].text OR delta.text

            text_piece = None

            if "choices" in chunk:
                c = chunk["choices"][0]

                if "text" in c:
                    text_piece = c["text"]

                if "delta" in c and "text" in c["delta"]:
                    text_piece = c["delta"]["text"]

            if text_piece:
                full_text += text_piece
                print(text_piece, end="", flush=True)

    print("\n\n=== RAW OUTPUT END ===")
    return full_text


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------

if __name__ == "__main__":

    convo = [{"role": "user", "content": TEST_PROMPT}]

    raw_output = run_raw_turn(convo)

    print("\n\n[FINAL RAW OUTPUT]")
    print(raw_output)
