import dotenv

dotenv.load_dotenv()
import os

config = {
    "together_api_key": os.getenv("TOGETHER_API_KEY"),
    "url": "https://api.together.xyz/v1/chat/completions",
    "model": "scb10x/scb10x-typhoon-2-1-gemma3-12b",
    "test_prompt": "Please fetch me the flight times between LAX and JFK. Use the get_flight_times tool.",
}
