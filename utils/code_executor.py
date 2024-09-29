from entities_api.clients.client import OllamaClient

# Initialize the OllamaClient (it will fetch the SANDBOX_SERVER_URL from the environment)
client = OllamaClient()

# Define a more complex Python code to be executed
python_code = """
def factorial(n):
    if n == 0 or n == 1:
        return 1
    else:
        result = 1
        for i in range(2, n + 1):
            result *= i
        return result

number = 10
print(f"Factorial of {number} is {factorial(number)}")
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

# Print the raw response from the server
print(response)

# Print the response (output or error)
if 'error' in response:
    print(f"Error: {response['error']}")
else:
    print(f"Output: {response['output']}")
