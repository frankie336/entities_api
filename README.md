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
import os

from dotenv import load_dotenv
from src.api.entities_api import InferenceFactory, OllamaClient


def initialize_services():
    """
    Initializes the necessary services by loading environment variables
    and creating an OllamaClient instance.

    Returns:
        OllamaClient: An instance of OllamaClient.

    Raises:
        EnvironmentError: If required environment variables are missing.
    """
    # Load environment variables from .env file
    load_dotenv()
    print("Environment variables loaded.")

    # Validate environment variables
    required_env_vars = ['ASSISTANTS_BASE_URL', 'API_KEY']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        print(f"Missing required environment variables: {', '.join(missing_vars)}")
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

    # Initialize OllamaClient
    client = OllamaClient()
    print("OllamaClient initialized.")

    return client


def create_entities(client):
    """
    Creates the necessary entities: user, assistant, thread, message, and run.

    Args:
        client (OllamaClient): The Ollama client instance.

    Returns:
        tuple: A tuple containing user, assistant, thread, message, and run objects.
    """
    # Create user
    user = client.user_service.create_user(name='test_user')
    print(f"User created: ID: {user.id}")

    # Create assistant
    assistant = client.assistant_service.create_assistant(
        name='Mathy',
        description='test_case',
        model='llama3.1',
        instructions='You are a helpful assistant'
    )
    print(f"Assistant created: ID: {assistant.id}")

    # Create thread
    thread = client.thread_service.create_thread(participant_ids=[user.id])
    print(f"Thread created: ID: {thread.id}")

    # Create Message
    message = client.message_service.create_message(
        thread_id=thread.id,
        content='Can you help me with a math problem?',
        role='user',
        sender_id=user.id
    )
    print(f"Message created: ID: {message['id']}")

    # Create Run
    run = client.run_service.create_run(thread_id=thread.id, assistant_id=assistant.id)
    print(f"Run created: ID: {run.id}")

    return user, assistant, thread, message, run


def conversation(client, thread_id, user_message, user_id, selected_model, inference_type='local'):
    """
    Initiates a conversation and processes the response in chunks.

    Args:
        client (OllamaClient): The Ollama client instance.
        thread_id (str): The ID of the thread.
        user_message (str): The user's message.
        user_id (str): The ID of the user.
        selected_model (str): The model to use for the assistant.
        inference_type (str): Type of inference ('local' or 'cloud').

    Returns:
        None
    """
    assistant_id = "asst_HAaA8ScjIR0wliE2ji0jpX"  # Replace with your actual assistant ID

    # Push the user message to the API DB
    the_message = client.message_service.create_message(
        thread_id=thread_id,
        content=user_message,
        role='user',
        sender_id=user_id
    )

    message_id = the_message['id']
    print(f"User message pushed: ID: {message_id}")

    # Create Run for the conversation
    run = client.run_service.create_run(thread_id=thread_id, assistant_id=assistant_id)
    print(f"Run created for conversation: ID: {run.id}")

    # Initialize Inference
    inference_factory = InferenceFactory()
    inference = inference_factory.get_inference(inference_type=inference_type, available_functions=None)
    print(f"Inference initialized with type: {inference_type}")

    try:
        # Determine the appropriate method based on inference type
        if inference_type.lower() == 'local':
            response_generator = inference.process_conversation(
                thread_id=thread_id,
                message_id=message_id,
                run_id=run.id,
                assistant_id=assistant_id,
                model=selected_model
            )
        elif inference_type.lower() == 'cloud':
            response_generator = inference.process_conversation(
                thread_id=thread_id,
                message_id=message_id,
                run_id=run.id,
                assistant_id=assistant_id,
                user_message=user_message
            )
        else:
            raise ValueError(f"Unsupported inference type: {inference_type}")

        # Process and print each chunk of the response
        for chunk in response_generator:
            print(chunk)  # Handle the chunk as needed

        print("[DONE]")
    except Exception as e:
        print(f"Error during conversation: {str(e)}")
        print("[ERROR]")


def main():
    """
    Main function to initialize services, create entities, and start a conversation.
    """
    try:
        # Initialize services
        client = initialize_services()

        # Create necessary entities
        user, assistant, thread, message, run = create_entities(client)

        # Define the user message
        user_message = 'Can you solve 32768 squared?'

        # Start the conversation
        conversation(
            client=client,
            thread_id=thread.id,
            user_message=user_message,
            user_id=user.id,
            selected_model='llama3.1',
            inference_type='local'  # Change to 'cloud' if needed
        )

    except EnvironmentError as env_err:
        print(f"Environment setup error: {env_err}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()

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
  
  [Vector Store](/docs/vector_store.md)
