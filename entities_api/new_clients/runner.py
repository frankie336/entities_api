import json
import os
import uuid
import collections
from flask import Response, stream_with_context
from dotenv import load_dotenv

# Import IBM Watson modules
from ibm_watsonx_ai import APIClient as WatsonAPIClient
from ibm_watsonx_ai.foundation_models import ModelInference as WatsonModelInference
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as WatsonGenParams
from ibm_watsonx_ai.foundation_models.utils.enums import DecodingMethods as WatsonDecodingMethods

# Importing services
from entities_api.new_clients.client_actions_client import ClientActionService
from entities_api.new_clients.client_assistant_client import ClientAssistantService
from entities_api.new_clients.client_message_client import ClientMessageService
from entities_api.new_clients.client_run_client import RunService
from entities_api.new_clients.client_thread_client import ThreadService
from entities_api.new_clients.client_tool_client import ClientToolService
from entities_api.new_clients.client_user_client import UserService
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class Runner:
    def __init__(self, base_url=os.getenv('ASSISTANTS_BASE_URL'), api_key=None, available_functions=None):
        self.base_url = base_url or os.getenv('ASSISTANTS_BASE_URL')
        self.api_key = api_key or os.getenv('API_KEY')
        self.user_service = UserService(self.base_url, self.api_key)
        self.assistant_service = ClientAssistantService(self.base_url, self.api_key)
        self.thread_service = ThreadService(self.base_url, self.api_key)
        self.message_service = ClientMessageService(self.base_url, self.api_key)
        self.run_service = RunService(self.base_url, self.api_key)
        self.tool_service = ClientToolService(self.base_url, self.api_key)
        self.action_service = ClientActionService(self.base_url, self.api_key)
        self.available_functions = available_functions or {}

        # Initialize IBM Watson API client (credentials should be stored securely in the .env file)
        self.watson_credentials = {
            "url": os.getenv('IBM_WATSON_URL'),
            "apikey": os.getenv('IBM_WATSON_APIKEY'),
        }
        self.watson_client = WatsonAPIClient(self.watson_credentials)
        self.project_id = os.getenv('IBM_WATSON_PROJECT_ID')

        # Initialize the model inference instance for Watson
        self.model = WatsonModelInference(
            model_id=self.watson_client.foundation_models.TextModels.LLAMA_3_2_90B_VISION_INSTRUCT,
            credentials=self.watson_credentials,
            project_id=self.project_id,
            verify=False,
        )

        logging_utility.info("Runner initialized with base_url: %s", self.base_url)

    def truncate_conversation_history(self, conversation_history, max_exchanges=10):
        """
        Truncates the conversation history to the specified number of exchanges.

        Args:
            conversation_history (list): The list of previous messages in the conversation.
            max_exchanges (int): The maximum number of user-assistant exchanges to retain.

        Returns:
            list: The truncated conversation history.
        """
        # Each exchange consists of two messages: User and Assistant
        max_messages = max_exchanges * 2
        if len(conversation_history) > max_messages:
            # Remove the oldest messages
            conversation_history = conversation_history[-max_messages:]
        return conversation_history

    def normalize_roles(self, conversation_history):
        """
        Normalizes the role names in the conversation history to ensure consistency.

        Args:
            conversation_history (list): The list of previous messages in the conversation.

        Returns:
            list: The conversation history with normalized role names.
        """
        normalized_history = []
        for message in conversation_history:
            role = message.get('role', '').strip().capitalize()
            if role not in ['User', 'Assistant', 'System']:
                role = 'User'  # Default to 'User' if role is unrecognized
            normalized_history.append({
                "role": role,
                "content": message.get('content', '').strip()
            })
        return normalized_history

    def process_conversation(self, thread_id, message_id, run_id, assistant_id, user_message):
        """
        Generates a response using IBM Watson LLM and yields it as chunks for streaming.
        Integrates conversation history handling with truncation.

        Args:
            thread_id (str): Identifier for the conversation thread.
            message_id (str): Identifier for the specific message.
            run_id (str): Identifier for the run instance.
            assistant_id (str): Identifier for the assistant.
            user_message (str): The latest message from the user.

        Yields:
            str: Chunks of the assistant's response.
        """
        # Define the system prompt
        system_prompt = "You are a helpful assistant that provides concise and informative answers."

        # Retrieve the formatted message history from the message service
        conversation_history = self.message_service.get_formatted_messages(
            thread_id, system_message=''
        )
        logging_utility.debug("Original formatted messages: %s", conversation_history)

        # Normalize roles to ensure consistency
        conversation_history = self.normalize_roles(conversation_history)
        logging_utility.debug("Normalized conversation history: %s", conversation_history)

        # Exclude system messages if any (since system_prompt is handled separately)
        conversation_history = [msg for msg in conversation_history if msg['role'] in ['User', 'Assistant']]
        logging_utility.debug("Filtered conversation history (User and Assistant only): %s", conversation_history)

        # Truncate the conversation history to maintain the last 10 exchanges
        conversation_history = self.truncate_conversation_history(conversation_history, max_exchanges=10)
        logging_utility.debug("Truncated conversation history: %s", conversation_history)

        # Check if the last message is the same as the new user message to prevent duplication
        if not (conversation_history and
                conversation_history[-1]['role'] == 'User' and
                conversation_history[-1]['content'] == user_message):
            # Append the new user message to the conversation history
            conversation_history.append({"role": "User", "content": user_message})
            logging_utility.debug("Appended new user message to conversation history.")
        else:
            logging_utility.debug("New user message already exists in conversation history. Skipping append.")

        # Start constructing the prompt with the system prompt and truncated conversation history
        prompt_txt = system_prompt + "\n\n"
        for message in conversation_history:
            prompt_txt += f"{message['role']}: {message['content']}\n"
        prompt_txt += "Assistant:"  # Ensure capitalization

        # Log the constructed prompt for debugging
        logging_utility.debug(f"Constructed Prompt:\n{prompt_txt}")

        # Generation parameters
        gen_parms = {
            WatsonGenParams.DECODING_METHOD: WatsonDecodingMethods.GREEDY,
            WatsonGenParams.MAX_NEW_TOKENS: 150,  # Adjust token length as needed
            WatsonGenParams.TEMPERATURE: 0.7  # Adjust temperature for creativity
        }

        assistant_reply = ""

        try:
            # GENERATE TEXT STREAM using the 'generate_text_stream' method
            logging_utility.info("Started generating response stream.")
            stream_response = self.model.generate_text_stream(prompt=prompt_txt, params=gen_parms)

            # Directly iterate over the generator
            for chunk in stream_response:
                if chunk.strip():  # Only yield non-empty chunks
                    assistant_reply += chunk
                    logging_utility.debug(f"Streaming chunk received: {chunk}")
                    yield chunk

        except Exception as e:
            error_message = "[ERROR] An error occurred during streaming."
            logging_utility.error(f"Error during streaming: {str(e)}", exc_info=True)
            yield error_message
            return  # Exit the generator after yielding the error
