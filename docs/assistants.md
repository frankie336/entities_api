# Assistants

## Overview

Create an Assistant by defining its custom instructions and picking a model. If helpful, add files and enable tools like Code Interpreter, File Search, and Function calling.


**Create an Assistant**

```python
from src.api.entities import CommonEntitiesInternalInterface

# Initialize the client
client = CommonEntitiesInternalInterface()

# Create user
user = client.user_service.create_user(name='test_user')
print(f"User created: ID: {user.id}")

User
created: ID: user_rr4NrmUbzwPO4l17rHFNDV

# Create assistant
assistant = client.assistant_service.create_assistant(
    name='Mathy',
    description='test_case',
    model='llama3.1',
    instructions='You are a helpful assistant'
)
print(f"Assistant created: ID: {assistant.id}")

Assistant
created: ID: asst_9MseFMx9MxLwazMSeal9i6
```



**Associate an Assistant with a User**

```python
associate = client.assistant_service.associate_assistant_with_user(
     assistant_id=assistant.id,
     user_id=user.id
 )
```



**Disassociate an Assistant with a User**

```python
disassociate = client.disassociate_assistant_from_user.associate_assistant_with_user(
     assistant_id=assistant.id,
     user_id=user.id
 )
```




**List assistants for the user**

```python

assistants = user_service.list_assistants_by_user(user_id=user.id)
```



Assistants can be associated to multiple Users

**Retrieve an Assistant**

```python

# Create assistant
assistant = client.assistant_service.retrieve_assistant(assistant_id=assistant.id) 
print(assistant.dict())

{'id': 'asst_CuNRAd8TuDurZbmtaFNrmE', 'user_id': None, 'object': 'assistant', 'created_at': 1726726621, 'name': 'Mathy', 'description': 'test_case', 'model': 'llama3.1', 'instructions': 'You are a helpful assistant', 'meta_data': None, 'top_p': 1.0, 'temperature': 1.0, 'response_format': 'auto'}

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
