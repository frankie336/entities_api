import json
import os
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

    def process_conversation(self,thread_id, message_id, run_id, assistant_id, user_message):

        """
        Generates a response using IBM Watson LLM and yields it as chunks for streaming.
        """
        # Define the system prompt
        system_prompt = "You are a helpful assistant that provides concise and informative answers."

        # Construct the prompt text
        prompt_txt = f"{system_prompt}\n\nUser: {user_message}\nAssistant:"

        # Generation parameters
        gen_parms = {
            WatsonGenParams.DECODING_METHOD: WatsonDecodingMethods.GREEDY,
            WatsonGenParams.MAX_NEW_TOKENS: 1000,
            WatsonGenParams.TEMPERATURE: 0.1
        }

        try:
            # Stream response using the 'generate_text_stream' method
            logging_utility.info("Started generating response stream.")
            stream_response = self.model.generate_text_stream(prompt=prompt_txt, params=gen_parms)

            for chunk in stream_response:
                if chunk.strip():  # Only yield non-empty chunks
                    logging_utility.debug(f"Streaming chunk received: {chunk}")
                    yield chunk

        except Exception as e:
            logging_utility.error(f"Error during streaming: {str(e)}", exc_info=True)
            yield "[ERROR] An error occurred during streaming."


