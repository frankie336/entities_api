import dotenv

dotenv.load_dotenv()
import os

config = {
    "together_api_key": "",
    "entities_api_key": "",
    "entities_user_id": "",
    "base_url": "http://localhost:9000",
    "url": "https://api.together.xyz/v1/chat/completions",
    "model": "hyperbolic/openai/gpt-oss-120b",
    "provider": "Hyperbolic",
    "assistant_id": "asst_13HyDgBnZxVwh5XexYu74F",
    "test_prompt": "Write a haiku about Python code.",
}
