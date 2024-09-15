from entities_api.new_clients.client import OllamaClient

# Initialize the OllamaClient (it will fetch the SANDBOX_SERVER_URL from the environment)
client = OllamaClient()

# Define the code to be executed
python_code = """
print("Hello from the sandbox!")
"""

# Define the user ID and language
user_id = "test_user"
language = "python"

# Execute the code using the code_executor_service
response = client.code_executor_service.execute_code(
    code=python_code,
    language=language,
    user_id=user_id
)

# Print the response (output or error)
if 'error' in response:
    print(f"Error: {response['error']}")
else:
    print(f"Output: {response['output']}")
