# Entities V1

The **Entities** API is for developing projects that interact with LLMs.
It aggregates inference calls to multiple providers as well as local using the [Ollama](https://github.com/ollama) library. 

This enables rapid and flexible deployment of advanced features such as conversation management, 
[function calling](/docs/function_calling.md), [code interpretation](/docs/function_calling.md), and more through easy-to-use API endpoints.


## Supported Inference Providers: 

| Provider                                       | Type                        |
|------------------------------------------------|-----------------------------|
| [Ollama](https://github.com/ollama)            | **Local** (Self-Hosted)     |
| [DeepSeek](https://platform.deepseek.com/)     | **Cloud** (Open-Source)     |
| [Hyperbolic](https://hyperbolic.xyz/)          | **Cloud** (Proprietary)     |
| [OpenAI](https://platform.openai.com/)         | **Cloud** (Proprietary)     |
| [together.ai](https://www.together.ai/)        | **Cloud** (Aggregated)      |
| [MS Azure Foundry](https://azure.microsoft.com) | **Cloud** (Enterprise)      |


## Why Entities API

The landscape of AI inference has become both competitive and diverse. Every month, a new AI lab or vertical provider announces a breakthrough or releases a new API offering. No single provider meets all requirements or interests, as each one offers a different API with its own keys, schemas, endpoints, and features. This diversity has quickly made AI inference cumbersome.

Entities API aggregates the core features and methodologies of all providers into one unified platform.

## State Management

Advanced applications and integrations in LLMs require state management, which is not always a trivial task.
For example, here is a typical LLM assistant's dialogue array:

For example,  here is a typical LLM assistant's dialogue array:

```json

[
  {
    "role": "system",
    "content": "You are a helpful assistant."
  },
  {
    "role": "user",
    "content": "What’s the capital of France?"
  },
  {
    "role": "assistant",
    "content": "The capital of France is Paris."
  },
  {
    "role": "user",
    "content": "What’s the population of Paris?"
  },
  {
    "role": "assistant",
    "content": "As of the latest data, the population of Paris is approximately 2.1 million."
  }
]

```

This array represents a single multi-turn conversation. In a production environment, the life cycle of this array must be managed per user, per conversation. This may require a database and other back-end infrastructure.
The Entities API [Threads](/docs/threads.md)  endpoint simplifies dialogue management by providing a standardized, data-driven setup and use procedure. Data storage and retrieval are handled by this endpoint.






## Install

```sh
tbc
```

## Quick Start

```python

# Import the public SDK interface.
from entities import Entities

client = Entities()
user = client.user.create_user(name='test_user')

thread = client.threads.create_thread(participant_ids=[user.id])

assistant = client.assistant.create_assistant()


message = client.messages.create_message(
    thread_id=thread.id,
    role='user',
    content='Hello, This is a test')

run = client.runs.create_run(assistant_id=assistant.id,
                             thread_id=thread.id,

                             )


try:
    completion = client.inference.create_completion(
        provider="Hyperbolic",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        thread_id=thread.id,
        message_id=message['id'],
        run_id=run.id,
        assistant_id=assistant.id
    )
    pprint.pprint(completion)
finally:
    pass



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
