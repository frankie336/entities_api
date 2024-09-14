import time

from entities_api.new_clients.client import OllamaClient

# Initialize the client
client = OllamaClient()

# Create a user
user = client.user_service.create_user(name='test_user')
user_id = user.id
print(f"User created with ID: {user_id}")

# Create a sandbox for the user
sandbox = client.sandbox_service.create_sandbox(
    user_id=user_id,
    name='test_sandbox',
    config={'language': 'python', 'version': '3.9'}
)

sandbox_id = sandbox.id
print(f"Sandbox created with ID: {sandbox_id}")

# Retrieve the sandbox
retrieved_sandbox = client.sandbox_service.get_sandbox(sandbox_id)
print(f"Retrieved Sandbox: {retrieved_sandbox}")


# Update the sandbox
updated_sandbox = client.sandbox_service.update_sandbox(
    sandbox_id=sandbox_id,
    name='updated_test_sandbox',
    config={'language': 'python', 'version': '3.10'}
)



# List sandboxes for the user
user_sandboxes = client.sandbox_service.list_sandboxes_by_user(user_id)
print(f"Sandboxes for user {user_id}:")
for sb in user_sandboxes:
    print(sb)



# Delete the sandbox
client.sandbox_service.delete_sandbox(sandbox_id)
print(f"Sandbox with ID {sandbox_id} deleted.")


# Verify deletion by attempting to retrieve the sandbox
try:
    client.sandbox_service.get_sandbox(sandbox_id)
except Exception as e:
    print(f"Sandbox retrieval after deletion failed as expected: {e}")





