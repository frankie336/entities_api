import json
import os
import re
from collections import defaultdict

import dotenv
import requests
from openai import OpenAI

# Load environment variables (API Keys)
dotenv.load_dotenv()

# --- CONFIGURATION ---
TARGET_FILE = "models.py"  # The file where the lists will be injected
HYPERBOLIC_BASE = "https://api.hyperbolic.xyz/v1"
TOGETHER_BASE = "https://api.together.xyz/v1"

# Keywords to exclude (Image/Video/Audio models)
EXCLUDED_KEYWORDS = ["StableDiffusion", "FLUX", "TTS", "SDXL", "diffusion"]


# --- FORMATTING HELPER ---
def generate_formatted_dict_string(models_list, provider_label):
    """
    Takes a list of model dicts and returns a formatted Python dictionary string
    grouped by Organization.
    """
    # Group by Organization (e.g., deepseek-ai, meta-llama)
    grouped = defaultdict(list)

    for item in models_list:
        # Parsing ID to get Org (e.g. "deepseek-ai/DeepSeek-V3")
        # We strip the provider prefix first so we can parse the raw ID for the Org name
        clean_id = item["id"].replace(f"{provider_label}/", "")

        if "/" in clean_id:
            org = clean_id.split("/")[0]
        else:
            org = "Other"
        grouped[org].append(item)

    # Build the Python dictionary string
    lines = ["{"]

    for org in sorted(grouped.keys()):
        lines.append(f"    # --- {org} ---")
        # Sort models alphabetically by their key/friendly name
        for m in sorted(grouped[org], key=lambda x: x["key"]):
            lines.append(f"    \"{m['key']}\": {{")
            lines.append(f"        \"id\": \"{m['id']}\",")
            lines.append(f"        \"provider\": \"{m['provider']}\",")
            lines.append(f"    }},")
        lines.append("")  # Spacer between groups

    lines.append("}")
    return "\n".join(lines)


# --- DATA FETCHERS ---


def get_hyperbolic_data():
    print("Fetching models from Hyperbolic...")
    try:
        api_key = os.getenv("HYPERBOLIC_API_KEY")
        if not api_key:
            print("Skipping Hyperbolic (No Key found in .env)")
            return []

        client = OpenAI(api_key=api_key, base_url=HYPERBOLIC_BASE)
        models = client.models.list()

        result_list = []
        for m in models.data:
            # 1. Filter garbage (Images, Audio, etc)
            if any(x in m.id for x in EXCLUDED_KEYWORDS):
                continue

            # 2. Logic: friendly name is last part
            friendly_name = m.id.split("/")[-1]

            # 3. Construct Payload with PREFIX
            result_list.append(
                {
                    "key": friendly_name,
                    "id": f"hyperbolic/{m.id}",  # <--- CRITICAL PREFIX
                    "provider": "hyperbolic",
                }
            )
        return result_list
    except Exception as e:
        print(f"Hyperbolic fetch failed: {e}")
        return []


def get_together_data():
    print("Fetching models from Together AI...")
    api_key = os.getenv("TOGETHER_API_KEY")
    if not api_key:
        print("Skipping Together (No Key found in .env)")
        return []

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.get(f"{TOGETHER_BASE}/models", headers=headers)
        response.raise_for_status()
        data = response.json()

        relevant_types = ["chat", "language", "code"]
        result_list = []

        for model in data:
            if model.get("type") in relevant_types:
                raw_id = model.get("id")

                # Logic: friendly name is last part
                friendly_name = raw_id.split("/")[-1]

                # Construct Payload with PREFIX
                result_list.append(
                    {
                        "key": friendly_name,
                        "id": f"together-ai/{raw_id}",  # <--- CRITICAL PREFIX
                        "provider": "together-ai",
                    }
                )
        return result_list
    except Exception as e:
        print(f"Together AI fetch failed: {e}")
        return []


# --- FILE UPDATER ---
def update_block(content, marker_start, marker_end, var_name, dict_string):
    """Replaces text between markers with the generated dict string."""
    new_block = f"{var_name} = {dict_string}"

    # Regex to find everything between markers
    pattern = rf"({re.escape(marker_start)})(.*?)({re.escape(marker_end)})"

    # Check if markers exist
    if not re.search(pattern, content, flags=re.DOTALL):
        print(f"Warning: Markers for {var_name} not found in {TARGET_FILE}.")
        return content

    # Replace
    return re.sub(pattern, f"\\1\n{new_block}\n\\2", content, flags=re.DOTALL)


def main():
    if not os.path.exists(TARGET_FILE):
        print(f"Critical Error: {TARGET_FILE} not found!")
        return

    # 1. Fetch Data
    hyper_list = get_hyperbolic_data()
    tog_list = get_together_data()

    # 2. Format Data (Convert list to the Python Dictionary String)
    print("Formatting data...")
    hyper_str = generate_formatted_dict_string(hyper_list, "hyperbolic")
    tog_str = generate_formatted_dict_string(tog_list, "together-ai")

    # 3. Read Target File
    print(f"Reading {TARGET_FILE}...")
    with open(TARGET_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # 4. Perform Updates
    print("Injecting new model lists...")
    content = update_block(
        content,
        "# --- TOGETHER_AI_MODELS_START ---",
        "# --- TOGETHER_AI_MODELS_END ---",
        "TOGETHER_AI_MODELS",
        tog_str,
    )

    content = update_block(
        content,
        "# --- HYPERBOLIC_MODELS_START ---",
        "# --- HYPERBOLIC_MODELS_END ---",
        "HYPERBOLIC_MODELS",
        hyper_str,
    )

    # 5. Write Back
    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n[SUCCESS] Synced models to {TARGET_FILE}")


if __name__ == "__main__":
    main()
