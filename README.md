# Ollama Entities Library

The **Ollama Entities** library is a state management and control API built on top of the [Ollama Python library](https://github.com/ollama/ollama-python). It offers an integrated API framework for developing projects that interact with open-source LLMs using the [Ollama](https://github.com/ollama) library. This enables rapid and flexible deployment of advanced features such as conversation management, [function calling](/docs/function_calling.md), [code interpretation](/docs/function_calling.md), and more through easy-to-use API endpoints.

This documentation assumes a working knowledge of the [Ollama](https://github.com/ollama) library.


## Supported Models

| Model     | Parameters | Size  | Download                  |
|-----------|------------|-------|---------------------------|
| Llama 3.1 | 8B         | 4.7GB | `ollama run llama3.1`      |
| Llama 3.1 | 70B        | 40GB  | `ollama run llama3.1:70b`  |
| Llama 3.1 | 405B       | 231GB | `ollama run llama3.1:405b` |

This library has been thoroughly tested with the models listed in the table above. Since the Ollama framework supports many more models, it should also work with additional ones. For an exhaustive list, refer to the [Ollama library documentation](https://github.com/ollama/ollama/blob/main/README.md) and the [definitive list of supported models](https://ollama.com/library).




## Install

```sh
tbc
```

## Quick Start

```python
import json
from flask import jsonify, request, Response, stream_with_context
from entities_api import OllamaClient  
from entities_api import InferenceFactory # the inference client
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

# Create Run
message_id = message.id  
run = client.run_service.create_run(thread_id=thread.id, assistant_id=assistant.id)  


print(f"Run created: ID: {run.id}")  # Optional: To confirm run creation

# Create a helper that streams the response 

def conversation(thread_id, user_message, user_id, selected_model):
    """
    Initiates a conversation and streams the response in chunks.

    Args:
        thread_id (str): The ID of the thread.
        user_message (str): The user's message.
        user_id (str): The ID of the user.
        selected_model (str): The model to use for the assistant.

    Returns:
        Response: A FastAPI Response object that streams the conversation.
    """
    
    def generate_chunks():
        
        inference_factory = InferenceFactory()
        inference = inference_factory.get_inference(inference_type='local', available_functions=None),
                
        
        try:
            # Yield the initial run_id
            yield f"data: {json.dumps({'run_id': run_id})}\n\n"

            # Stream chunks as conversation progresses
            for chunk in inference.runner.process_conversation(
                thread_id=thread_id, 
                message_id=message_id, 
                run_id=run.id,
                assistant_id=assistant.id, 
                model=selected_model
            ):
                logging_utility.debug(f"Received chunk: {chunk}")  # ✅ Ensure 'logging_utility' is defined
                json_chunk = {"chunk": chunk}
                yield f"data: {json.dumps(json_chunk)}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            logging_utility.error(f"Error during conversation: {str(e)}")  # ✅ Ensure 'logging_utility' is defined
            yield "data: [ERROR]\n\n"

    return Response(stream_with_context(generate_chunks()), content_type='text/event-stream')  # ✅ Ensure necessary imports

# Example usage of the conversation helper (if applicable)
# response = conversation(thread.id, 'Can you solve 32768 squared?', user.id, 'llama3.1')
```

Whilst it involves a little more effort, adding state management to distinct parts of the LLM/User interaction life cycle brings significant benefits. By pragmatically interacting with each stage, you can unlock an @OpenAI type feature set with minimal additional coding.





## Documentation

  [Assistants](/docs/assistants.md)
  
  [Code Interpretation](/docs/code_interpretation.md)
  
  [Function Calling](/docs/function_calling.md)
  
  [Inference](/docs/inference.md)
  
  [Messages](/docs/messages.md)
  
  [Runs](/docs/runs.md)

  [Threads](/docs/threads.md)
  
  [Users](/docs/users.md)
