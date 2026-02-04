import dotenv
import os

dotenv.load_dotenv()

config = {
    "together_api_key": os.getenv("TOGETHER_API_KEY"),
    "entities_api_key": "",
    "entities_user_id": "",
    "base_url": "http://localhost:9000",
    "url": "https://api.together.xyz/v1/chat/completions",
    "model": "together-ai/deepcogito/cogito-v2-1-671b",
    "provider": "Hyperbolic",
    "assistant_id": "asst_13HyDgBnZxVwh5XexYu74F",
    "test_prompt": "Please fetch me the flight times between LAX and JFK.",
}
