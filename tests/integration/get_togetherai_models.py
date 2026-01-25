import json
import os
from collections import defaultdict

import requests
from dotenv import find_dotenv, load_dotenv

# 1. Load API Key
load_dotenv(find_dotenv())
API_KEY = os.getenv("TOGETHER_API_KEY")

if not API_KEY:
    print("Error: TOGETHER_API_KEY not found in environment variables.")
    exit(1)


def get_together_models():
    print("Fetching model list from Together AI API...")

    url = "https://api.together.xyz/v1/models"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        # Together returns a list of dictionaries
        # We generally only care about 'chat' or 'language' models for the Orchestrator
        # (Filtering out image/embedding models to keep the list clean)
        relevant_types = ["chat", "language"]

        models_by_org = defaultdict(list)

        for model in data:
            model_type = model.get("type", "unknown")
            model_id = model.get("id")

            if model_type in relevant_types:
                # Group by Organization (e.g., 'meta-llama', 'deepseek-ai')
                # Model IDs look like: "meta-llama/Llama-3-70b-chat-hf"
                org = model_id.split("/")[0] if "/" in model_id else "Other"
                models_by_org[org].append(model_id)

        return models_by_org

    except Exception as e:
        print(f"Failed to fetch models: {e}")
        return None


def main():
    models = get_together_models()

    if not models:
        return

    print(f"\n{'='*60}")
    print(f"TOGETHER AI MODEL ENDPOINTS (Formatted for Config)")
    print(f"{'='*60}\n")

    # Sort organizations alphabetically
    for org in sorted(models.keys()):
        print(f"    # --- {org} ---")

        # Sort models alphabetically within org
        for model_id in sorted(models[org]):
            # Generate a readable label key (e.g., "deepseek-ai/DeepSeek-V3" -> "DeepSeek-V3")
            # This helps you populate your dictionary keys faster
            try:
                label = model_id.split("/")[-1]
            except:
                label = model_id

            print(f'    "{label}": "{model_id}",')

        print()  # Spacer between groups


if __name__ == "__main__":
    main()
