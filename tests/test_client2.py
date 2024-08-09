from assisants_api_life_cycle_test import OllamaClient, setup_user, setup_thread



# Define the base URL and API key
base_url = "http://localhost:8000/v1"

ollama_client = OllamaClient(api_key='your_api_key', base_url=base_url)

api_key = "your_api_key"

# Initialize the OllamaClient
client = OllamaClient(base_url=base_url, api_key=api_key)

# Create a user (this step is necessary because a thread requires a user)
user_name = "Student"
user_id = setup_user(client, user_name)

# Create a thread for the user
thread_id = setup_thread(client, user_id)
print(f"Created thread with ID: {thread_id}")
