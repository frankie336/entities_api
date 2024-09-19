# Assistants

## Overview

Create an Assistant by defining its custom instructions and picking a model. If helpful, add files and enable tools like Code Interpreter, File Search, and Function calling.


**Create an Assistant**

```python
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

Assistant created: ID: asst_9MseFMx9MxLwazMSeal9i6
```



**Retrieve an Assistant**

```python
print(f"User created: ID: {user.id}")

# Create assistant
assistant = client.assistant_service.retrieve_assistant(assistant_id=assistant.id) 
print(assistant.dict())

{'id': 'asst_CuNRAd8TuDurZbmtaFNrmE', 'user_id': 'user_U9BIqd2ZpzdFh7VF9HHla0', 'object': 'assistant', 'created_at': 1726726621, 'name': 'Mathy', 'description': 'test_case', 'model': 'llama3.1', 'instructions': 'You are a helpful assistant', 'meta_data': None, 'top_p': 1.0, 'temperature': 1.0, 'response_format': 'auto'}

```



**Update an Assistant**

```python

# Create assistant
client.assistant_service.delete(assistant_id=assistant.id) 
print(assistan# Create assistant
client.assistant_service.update_assistant(
    assistant_id=assistant.id,
    description='test_update',
    instructions='You are my Math teacher'
)


```


**Delete an Assistant**

```python

# Create assistant
client.assistant_service.delete(assistant_id=assistant.id) 
print(assistant)
```
