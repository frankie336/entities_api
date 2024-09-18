# Assistants

## Overview

Create an Assistant by defining its custom instructions and picking a model. If helpful, add files and enable tools like Code Interpreter, File Search, and Function calling.


**Creat

```python
from entities_api import OllamaClient  
from entities_api.services.logging_service import LoggingUtility  # Ensure logging utility is correctly imported

# Initialize the logging utility
logging_utility = LoggingUtility()

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
```