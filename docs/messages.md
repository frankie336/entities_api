# Messages

## Overview
The Ollama Entities library’s Messages endpoint allows you to create, retrieve, and update messages within conversations. With this endpoint, you can:

Create new messages with specified content, role (e.g., user or assistant), and sender ID.
Retrieve existing message information by ID.
Update message details, such as content or status.
By leveraging the Messages endpoint, you can manage the flow of conversation and interaction between users and assistants, enabling more sophisticated and context-aware conversations.


**Create a Message**

```python


from src.api.entities import CommonEntitiesInternalInterface

# Initialize the client
client = CommonEntitiesInternalInterface()

# Create user
user = client.user_service.create_user(name='test_user')

# Create thread
thread = client.thread_service.create_thread(participant_ids=[user.id])

# Create Message
message = client.message_service.create_message(
    thread_id=thread.id,
    content='Can you help me with a math problem?',
    role='user',
    sender_id=user.id
)

print(f"Message created: ID: {message.id}")  # Optional: To confirm message creation

```


**Retrieve a Message**
```python

message = client.message_service.retrieve_message(message_id=message.id)


```


**Update a Message**
```python

message = client.message_service.update_message(message_id=message.id
                                                content='Can you tell me more?',
                                                role='user',
                                                sender_id=user.id
                                                )


```








