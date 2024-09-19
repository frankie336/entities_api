from entities_api import OllamaClient
# Initialize the client
client = OllamaClient()

# Create user
user = client.user_service.create_user(name='test_user')

print(f"User created: ID: {user.id}")

# Create assistant
assistant = client.assistant_service.create_assistant(
    user_id=user.id,
    name='Mathy',
    description='test_case',
    model='llama3.1',
    instructions='You are a helpful assistant'
)
print(f"Assistant created: ID: {assistant.id}")


print(f"User created: ID: {user.id}")

# Create assistant
assistant = client.assistant_service.retrieve_assistant(assistant_id=assistant.id)
print(assistant.dict())



# Create assistant
client.assistant_service.update_assistant(
    assistant_id=assistant.id,
    description='test_update',
    instructions='You are my Math teacher'
)

assistant = client.assistant_service.retrieve_assistant(assistant_id=assistant.id)
print(assistant.dict())

all = client.assistant_service.list_assistants()
print(all)