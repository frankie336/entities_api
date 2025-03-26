# Inference

## Overview

Inference is the final stage of the Entities API workflow, where the assistant processes a prompt and generates a reply. This stage is where the magic happens, and the assistant’s intelligence is put to the test. Inference can be performed on edge devices or in the cloud, depending on your specific requirements and constraints. Our API supports both options, allowing you to choose the best approach for your use case.

## Local Inference

**Import the Inference Client**

```python
from src.api.entities import CommonEntitiesInternalInterface  # the state client  
from src.api.entities import InferenceFactory  # the inference client

```

**Set up the Inference Factory**
```python
inference_factory = InferenceFactory()
```

**Set up the Inference Factory**
```python
inference = inference_factory.get_inference(inference_type='local', available_functions=None)
```

## Cloud Inference

```python
inference = inference_factory.get_inference(inference_type='cloud', available_functions=None)
```
More Cloud based inference end points will be added.




**Generate Response**
```python

response_generator = inference.process_conversation(
                    thread_id=thread_id,
                    message_id=message_id,
                    run_id=run.id,
                    assistant_id=assistant_id,
                    user_message=user_message
                )
```

The steps above have been simplified for clarity. Here is the full workflow:

```python

# routes.py

import concurrent.futures
import json
import os  # Added for environment variables

from flask import jsonify, request, Response, stream_with_context
from flask_jwt_extended import jwt_required

from src.api.entities import InferenceFactory

from src.api.entities import code_interpreter
from src.api.entities import CommonEntitiesInternalInterface

client = CommonEntitiesInternalInterface()

from backend.app.services.function_call_service.handlers.temp_function_handlers import (
    get_flight_times,
    getAnnouncedPrefixes,
    create_libreoffice_document
)
from backend.app.services.logging_service.logger import LoggingUtility
from . import bp_llama

from dotenv import load_dotenv
from functools import lru_cache

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()

# Validate environment variables
required_env_vars = ['ASSISTANTS_BASE_URL', 'API_KEY']
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    logging_utility.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Define available functions for tool calls
available_functions = {
    'get_flight_times': get_flight_times,
    'getAnnouncedPrefixes': getAnnouncedPrefixes,
    'code_interpreter': code_interpreter,
    # 'create_libreoffice_document': create_libreoffice_document  # Uncomment if needed
    # Add other functions as needed
}


@lru_cache(maxsize=2)  # Adjust maxsize based on the number of inference types
def get_inference_instance(inference_type):
    return InferenceFactory.get_inference(inference_type, available_functions=available_functions)


@bp_llama.route('/api/messages/process', methods=['POST'])
@jwt_required()
def process_messages():
    logging_utility.info(f"Request data: {request.json}")
    logging_utility.info(f"Headers: {request.headers}")

    try:
        data = request.json

        # Handle both camelCase and snake_case
        messages = data.get('messages', [])
        user_id = data.get('userId') or data.get('user_id')
        thread_id = data.get('threadId') or data.get('thread_id')
        selected_model = data.get('model', 'llama3.1')
        inference_type = data.get('inferenceType') or data.get('inference_type', 'local')  # New

        logging_utility.info(
            f"Incoming request: user_id={user_id}, thread_id={thread_id}, model={selected_model}, inference_type={inference_type}")

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid or missing 'messages' in request")

        user_message = messages[0].get('content', '')
        if not user_message:
            raise ValueError("Message content is missing")

        logging_utility.info(f"Processing conversation for thread ID: {thread_id}")

        # Initialize the Inference instance using the factory (with caching)
        try:
            inference = get_inference_instance(inference_type)
            logging_utility.info(f"Inference instance created: {inference_type}")
        except ValueError as ve:
            logging_utility.error(f"Failed to create Inference instance: {ve}")
            return jsonify({'error': f"Unsupported inference type: {inference_type}"}), 400

        # Use ThreadPoolExecutor to run the check_and_update_pending_actions function in the background
        executor = concurrent.futures.ThreadPoolExecutor()
        # Pass the Inference instance to the background function
        executor.submit(check_and_update_pending_actions, thread_id, inference)

        # Pass the Inference instance and inference_type to the conversation function
        inference_factory = InferenceFactory()
        response = conversation(
            inference=inference_factory.get_inference(inference_type='cloud', available_functions=None),
            # TODO: pass the inbound inference_type
            thread_id=thread_id,
            user_message=user_message,
            user_id=user_id,
            selected_model=selected_model,
            inference_type=inference_type  # Pass the inference_type
        )
        return response

    except ValueError as ve:
        logging_utility.error(f"Validation error in process_messages: {str(ve)}")
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        logging_utility.error(f"Error in process_messages: {str(e)}")
        return jsonify({'error': 'An error occurred while processing the message'}), 500


def check_and_update_pending_actions(thread_id, inference):
    logging_utility.info("Checking for pending actions with thread_id: %s", thread_id)

    try:
        # Example implementation; adjust based on your actual logic
        pending_actions = inference.action_service.get_actions_by_status(thread_id=thread_id, status="pending")
        logging_utility.info("Retrieved %d pending actions for thread_id: %s", len(pending_actions), thread_id)

        if pending_actions:
            for action in pending_actions:
                logging_utility.debug("Pending action: ID=%s, Details=%s", action.get('id'), action)
                # Implement your action handling logic here
        else:
            logging_utility.info("No pending actions found for thread_id: %s", thread_id)
    except Exception as e:
        logging_utility.error("Error occurred while retrieving pending actions for thread_id %s: %s", thread_id, str(e))
        raise  # Re-raise the exception after logging


def conversation(thread_id, user_message, user_id, selected_model, inference, inference_type='cloud'):
    assistant_id = "asst_HAaA8ScjIR0wliE2ji0jpX"  # Ensure you use the correct assistant ID

    # Build the inbound user message
    # Pushes the message to API DB
    the_message = client.message_service.create_message(
        thread_id=thread_id,
        content=user_message,
        role='user',
        sender_id=user_id
    )

    # We need to set the inference end point here using the factory!
    # Only inference is handled by the factory
    # set up and state is handled by client

    message_id = the_message['id']
    run = client.run_service.create_run(thread_id=thread_id, assistant_id=assistant_id)

    # Build the payload and pass IDs to fetch conversation details from the API
    def generate_chunks():
        try:
            # Yield the initial run information
            yield f"data: {json.dumps({'run_id': run.id})}\n\n"

            # Stream the conversation chunks based on inference type
            if inference_type.lower() == 'local':
                # For DeepSeekR1Local, specify model if necessary
                response_generator = inference.process_conversation(
                    thread_id=thread_id,
                    message_id=message_id,
                    run_id=run.id,
                    assistant_id=assistant_id,
                    user_message=user_message
                    # model=selected_model
                )
            elif inference_type.lower() == 'cloud':
                # For CloudInference, pass the user_message
                response_generator = inference.process_conversation(
                    thread_id=thread_id,
                    message_id=message_id,
                    run_id=run.id,
                    assistant_id=assistant_id,
                    user_message=user_message
                )
            else:
                raise ValueError(f"Unsupported inference type: {inference_type}")

            # Handling chunks similarly to the previous version
            for chunk in response_generator:
                logging_utility.debug(f"Received chunk: {chunk}")

                # Ensure each chunk is wrapped in JSON before yielding
                json_chunk = {"chunk": chunk}
                yield f"data: {json.dumps(json_chunk)}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            logging_utility.error(f"Error during conversation: {str(e)}", exc_info=True)
            yield "data: [ERROR]\n\n"

    return Response(stream_with_context(generate_chunks()), content_type='text/event-stream')

```