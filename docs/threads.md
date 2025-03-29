# Threads

## Overview

A thread represents the conversation dialogue between a user and an assistant, providing a coherent data structure for conversation state management.

Multiple assistants can access the same thread, enabling seamless conversation continuity.
Threads facilitate ready-to-use conversation context, making it easier to manage complex interactions.


**Create a Thread**

```python
from src.api.entities import CommonEntitiesInternalInterface

thread = client.thread_service.create_thread(participant_ids=[user.id])
print(thread.dict())

{'id': 'thread_vLbg2nyS2WqqbbxlMELylH', 'created_at': 1726626670, 'meta_data': {'topic': ''}, 'object': 'thread',
 'tool_resources': {}}

```

Please see [here](docs/users.md) for instructions on creating users.


**List Threads by [User](docs/users.md)**

```python
from src.api.entities import CommonEntitiesInternalInterface

threads = client.thread_service.list_threads(user_id=user.id)
print(threads)

['thread_xhxuh7xjL9W0obWJYEyr6z']
```

You can fetch the conversation history of a thread with:

```python
from src.api.entities import CommonEntitiesInternalInterface

messages = client.message_service.list_messages(thread_id=thread.id)

[{'id': 'message_ok2GDPEHsN1FyFNIux5I8G', 'assistant_id': None, 'attachments': [], 'completed_at': None,
  'content': 'Hello', 'created_at': 1726624506, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {},
  'object': 'message', 'role': 'user', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'user_8tYOlZFZ36TDirMUbGvJ9g'},
 {'id': 'message_zu62jnO6LovGomjBwb1njb', 'assistant_id': 'assistant_id', 'attachments': [], 'completed_at': 1726624511,
  'content': "Hello! It's nice to meet you. I'm Nexa, and I'm here to help with any", 'created_at': 1726624511,
  'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message', 'role': 'assistant',
  'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN', 'sender_id': 'assistant'},
 {'id': 'message_QGpScM8Old8GGGr9v8deXi', 'assistant_id': None, 'attachments': [], 'completed_at': None,
  'content': 'Thanks Nexa,  this is Francis, your developer talking', 'created_at': 1726624540, 'incomplete_at': None,
  'incomplete_details': None, 'meta_data': {}, 'object': 'message', 'role': 'user', 'run_id': None, 'status': None,
  'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN', 'sender_id': 'user_8tYOlZFZ36TDirMUbGvJ9g'},
 {'id': 'message_jHG1ySMUBeXpgZqw5DZRH9', 'assistant_id': 'assistant_id', 'attachments': [], 'completed_at': 1726624545,
  'content': "Nice to talk to you too, Francis! How can I assist you today? Are there any updates or changes you'd like me to be aware of? \n\n(And just a heads up, I've checked our message history and it looks like we're starting fresh, so feel free to guide me on what we were working on last time if needed!)",
  'created_at': 1726624545, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'assistant', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'assistant'},
 {'id': 'message_mYoVK9deso7LOnKZRCJpKv', 'assistant_id': None, 'attachments': [], 'completed_at': None,
  'content': 'Excellent Nexa, I need your help to test int interuptt button feature on your front end user interface that I have made for you, please send me a long stream of text, like some essay on time travel or something like that',
  'created_at': 1726624640, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'user', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'user_8tYOlZFZ36TDirMUbGvJ9g'},
 {'id': 'message_vSnKsWsPIdIBcL8bAx38ef', 'assistant_id': 'assistant_id', 'attachments': [], 'completed_at': 1726624643,
  'content': 'Francis! I\'d be happy to help you test the interrupt button feature.\n\nHere\'s a lengthy passage on time travel:\n\n"Time travel, a staple of science fiction for centuries, has long been a topic of fascination and debate among physicists and theorists. The concept of traversing the fabric of',
  'created_at': 1726624643, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'assistant', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'assistant'},
 {'id': 'message_zCWromrtimlyHoG4TdIMEM', 'assistant_id': None, 'attachments': [], 'completed_at': None,
  'content': 'Excellent, that worked. Please send me an example of a python function', 'created_at': 1726624664,
  'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message', 'role': 'user',
  'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'user_8tYOlZFZ36TDirMUbGvJ9g'},
 {'id': 'message_6bp0Vv83SQuR6mtGvQe3n3', 'assistant_id': 'assistant_id', 'attachments': [], 'completed_at': 1726624670,
  'content': "Francis! I've checked our message history, and it seems like you're looking for a Python function to test with the code",
  'created_at': 1726624670, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'assistant', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'assistant'},
 {'id': 'message_FqOd9XKW0E8unlJNTKH3aS', 'assistant_id': None, 'attachments': [], 'completed_at': None,
  'content': 'Excellent, please send me another example of a python function.', 'created_at': 1726624717,
  'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message', 'role': 'user',
  'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'user_8tYOlZFZ36TDirMUbGvJ9g'},
 {'id': 'message_6LzeI0dUj0oNuYrcEHW6wD', 'assistant_id': 'assistant_id', 'attachments': [], 'completed_at': 1726624723,
  'content': 'Since you\'re testing the interrupt button feature, let\'s create a simple function that allows us to print out parts of a long string when we press the interrupt button.\n\nHere\'s an example Python function:\n\n```python\ndef print_string_chunk(string, chunk_size=100):\n    for i in range(0, len(string), chunk_size):\n        print(string[i:i+chunk_size])\n\n# Test with our earlier time travel passage\nprint_string_chunk("Time travel, a staple of science fiction for centuries, has long been a topic of fascination and',
  'created_at': 1726624723, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'assistant', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'assistant'},
 {'id': 'message_Jvpzi9UMFvyK9WEzc4q32E', 'assistant_id': None, 'attachments': [], 'completed_at': None,
  'content': 'Excellent, thanks Nexa!', 'created_at': 1726624738, 'incomplete_at': None, 'incomplete_details': None,
  'meta_data': {}, 'object': 'message', 'role': 'user', 'run_id': None, 'status': None,
  'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN', 'sender_id': 'user_8tYOlZFZ36TDirMUbGvJ9g'},
 {'id': 'message_BtqSPvAuYsS58JdkmauHh5', 'assistant_id': 'assistant_id', 'attachments': [], 'completed_at': 1726624744,
  'content': "You're welcome, Francis! I'm glad the Python function worked as expected. If you need any more help or want to test another feature, just let me know!\n\n(And don't forget, if there's an error with output from code_interpreter, please state the result instead of simulating output)",
  'created_at': 1726624744, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'assistant', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'assistant'},
 {'id': 'message_hrtzcE1rhl9Kn6Q3dHUx7O', 'assistant_id': None, 'attachments': [], 'completed_at': None,
  'content': 'Please prove to me that the code_interpreter tool is in good working order', 'created_at': 1726625452,
  'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message', 'role': 'user',
  'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'user_8tYOlZFZ36TDirMUbGvJ9g'},
 {'id': 'message_4lalK5iReI8BgFSOB9r0sf', 'assistant_id': None, 'attachments': [], 'completed_at': 1726625457,
  'content': '{"result": {"code": "print(\'Hello, World!\')", "output": "Hello, World!"}}', 'created_at': 1726625457,
  'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message', 'role': 'tool',
  'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN', 'sender_id': 'tool'},
 {'id': 'message_xnPtRNaI3xGTBYeqDPiiqy', 'assistant_id': 'assistant_id', 'attachments': [], 'completed_at': 1726625461,
  'content': 'Let\'s verify this with a Python function. We\'ll use the `code_interpreter` tool to execute it.\n\n```python\ndef hello_world():\n    return code_interpreter("print(\'Hello, World!\')")\n    \nhello_world()\n```\n\nIf everything is working correctly, this should print "Hello, World!"',
  'created_at': 1726625461, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'assistant', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'assistant'},
 {'id': 'message_Lz16frSSXRlkHtv4cgMg9I', 'assistant_id': None, 'attachments': [], 'completed_at': None,
  'content': 'Thanks', 'created_at': 1726625489, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {},
  'object': 'message', 'role': 'user', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'user_8tYOlZFZ36TDirMUbGvJ9g'},
 {'id': 'message_DtCBcaDNsd6aONGx63IS8G', 'assistant_id': 'assistant_id', 'attachments': [], 'completed_at': 1726625496,
  'content': "It was my pleasure to assist you. If you have any other questions or need further help, don't hesitate to ask.\n\n(And remember, Francis, if there's an issue with code_interpreter, I'll be sure to state the result instead of simulating output)",
  'created_at': 1726625496, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'assistant', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'assistant'},
 {'id': 'message_WYvv5fihNQmxrsHg5ctXFy', 'assistant_id': None, 'attachments': [], 'completed_at': None,
  'content': 'I am writing theads.md documentation for the Control API we use for you, which I have made open source. How does this read for the overview section: A thread represents the conversation dialogue between a user and an assistant. Threads can be leveraged to create a coherent data structure that represents the conversation and context between a user and the assistant, providing ready to use conversation state management.\n\n    • The same thread can be accessed by multiple assistants',
  'created_at': 1726625866, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'user', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'user_8tYOlZFZ36TDirMUbGvJ9g'},
 {'id': 'message_ueq6Jp8srm8TVdIRfQDVYS', 'assistant_id': None, 'attachments': [], 'completed_at': 1726625871,
  'content': '{"error": "Flight not found"}', 'created_at': 1726625871, 'incomplete_at': None,
  'incomplete_details': None, 'meta_data': {}, 'object': 'message', 'role': 'tool', 'run_id': None, 'status': None,
  'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN', 'sender_id': 'tool'},
 {'id': 'message_YnZF6CfVR966nIGTEN2cMx', 'assistant_id': 'assistant_id', 'attachments': [], 'completed_at': 1726625875,
  'content': "It looks like there's an issue with the code_interpreter tool.\n\nLet me try again with some text-based input. It seems that your markdown document for the Control API is looking good so far!\n\nHere's a possible revision to make it more concise and clear:\n\n**Overview**\n\nA thread represents the conversation dialogue between a user and an assistant, providing a coherent data structure for conversation state management.\n\n* Multiple assistants can access the same thread, enabling seamless conversation continuity.\n* Threads facilitate ready-to-use conversation context, making it easier to manage complex interactions.\n\nDoes this revised version look good to you?",
  'created_at': 1726625875, 'incomplete_at': None, 'incomplete_details': None, 'meta_data': {}, 'object': 'message',
  'role': 'assistant', 'run_id': None, 'status': None, 'thread_id': 'thread_Vg3trkDAYOJM7CSwOfN9TN',
  'sender_id': 'assistant'}]
```



**Delete a Thread**

```python
from src.api.entities import CommonEntitiesInternalInterface

thread = client.thread_service.delete_thread(thread_id='thread_vLbg2nyS2WqqbbxlMELylH')
```