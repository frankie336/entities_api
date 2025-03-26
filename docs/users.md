# Users

## Overview


The Entities API provides a comprehensive platform for managing interactions with users across various components:


*   The user object ties together the other components of the Entities API:
    *   Assistants
    *   Messages
    *   Threads
    *   Runs

This provides a robust and efficient user management system that can be used to securely segment users in any LLM project, enabling features like multi-user support, personalized experiences, and more.

**Make a User**

# Create user

```python
from entities import CommonEntitiesInternalInterface

# Initialize the client
client = CommonEntitiesInternalInterface()

user = client.user_service.create_user(name='test_user')
print(f"User created: ID: {user.id}")

User
created: ID: user_MCyFabmTVJbIkG7zfEvp44
```

**Retrieve a User**
```python

user = client.user_service.retrieve_user( user_id='user_MCyFabmTVJbIkG7zfEvp44') 
print(user.dict())

{'id': 'user_MCyFabmTVJbIkG7zfEvp44', 'name': 'test_user'}
```



**Update a USer**
```python

user = client.user_service.update_user(user_id='user_MCyFabmTVJbIkG7zfEvp44',
            name='new_user'
            )

```


**Delete a  User**

```python

client.user_service.delete_user(user_id='user_MCyFabmTVJbIkG7zfEvp44')

```