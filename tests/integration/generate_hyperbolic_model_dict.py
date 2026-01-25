import json
import os

import dotenv
from openai import OpenAI

# Load environment variables
dotenv.load_dotenv()

API_KEY = os.getenv("HYPERBOLIC_API_KEY")
if not API_KEY:
    raise ValueError("HYPERBOLIC_API_KEY not found in environment.")

client = OpenAI(api_key=API_KEY, base_url="https://api.hyperbolic.xyz/v1")


def generate_hyperbolic_model_dict():
    try:
        # 1. Fetch the list of models
        models = client.models.list()

        hyperbolic_models = {}

        # 2. Iterate and transform
        for model in models.data:
            model_id = model.id

            # Create a "friendly name" key (e.g., "deepseek-ai/DeepSeek-V3" -> "DeepSeek-V3")
            # We take the last part of the path as the key
            friendly_name = model_id.split("/")[-1]

            # Map to your specific data structure
            hyperbolic_models[friendly_name] = {
                "id": model_id,
                "provider": "hyperbolic",
            }

        # 3. Print the result in a copy-pasteable format
        # Or you could write this directly to a .py file
        print("HYPERBOLIC_MODELS = {")
        for key, value in hyperbolic_models.items():
            print(f"    '{key}': {json.dumps(value, indent=8).strip()[:-1]}    }},")
        print("}")

        return hyperbolic_models

    except Exception as e:
        print(f"Error fetching models: {e}")


if __name__ == "__main__":
    generate_hyperbolic_model_dict()
