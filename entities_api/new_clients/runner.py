import json
import os

from dotenv import load_dotenv
from ollama import Client

# Import the IBM Watson modules
from ibm_watsonx_ai import APIClient as WatsonAPIClient
from ibm_watsonx_ai.foundation_models import ModelInference as WatsonModelInference
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as WatsonGenParams
from ibm_watsonx_ai.foundation_models.utils.enums import DecodingMethods as WatsonDecodingMethods

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
        self.ollama_client = Client()
        self.tool_service = ClientToolService(self.base_url, self.api_key)
        self.action_service = ClientActionService(self.base_url, self.api_key)
        self.available_functions = available_functions or {}

        # Initialize IBM Watson API client (credentials should be stored securely)
        self.watson_credentials = {
            "url": os.getenv('IBM_WATSON_URL'),        # Set this in your .env file
            "apikey": os.getenv('IBM_WATSON_APIKEY'),  # Set this in your .env file
        }
        self.watson_client = WatsonAPIClient(self.watson_credentials)

        # Retrieve project_id from environment variables
        self.project_id = os.getenv('IBM_WATSON_PROJECT_ID')  # Set this in your .env file

        logging_utility.info("Runner initialized with base_url: %s", self.base_url)

    def create_tool_filtering_messages(self, messages):
        logging_utility.info("Creating tool filtering messages")
        logging_utility.debug("Original messages: %s", messages)

        system_message = next((msg for msg in messages if msg['role'] == 'system'), None)
        last_user_message = next((msg for msg in reversed(messages) if msg['role'] == 'user'), None)

        if not system_message or not last_user_message:
            logging_utility.warning("Could not find necessary messages for filtering. Using original messages.")
            return messages  # Return original if we can't find necessary messages

        filtered_messages = [system_message, last_user_message]
        logging_utility.info("Created filtered messages for tool calls")
        logging_utility.debug("Filtered messages: %s", filtered_messages)

        return filtered_messages

    def process_tool_calls(self, run_id, tool_calls, message_id, thread_id):
        """
        Processes tool calls and waits for status to change to 'ready'.
        Returns the response of tool functions, filtering out errors.
        """
        tool_results = []
        try:
            for tool in tool_calls:
                function_name = tool['function']['name']
                function_args = tool['function']['arguments']

                logging_utility.info(f"Function call triggered for run_id: {run_id}, function_name: {function_name}")

                # Look up tool by name
                tool_record = self.tool_service.get_tool_by_name(function_name)
                if not tool_record:
                    raise ValueError(f"Tool with name '{function_name}' not found")

                tool_id = tool_record.id  # Use tool_id

                # Create the action for the tool call
                action_response = self.action_service.create_action(
                    tool_name=function_name,
                    run_id=run_id,
                    function_args=function_args
                )

                logging_utility.info(f"Created action for function call: {action_response.id}")

                # Execute the corresponding function
                if function_name in self.available_functions:
                    function_to_call = self.available_functions[function_name]
                    try:
                        function_response = function_to_call(**function_args)
                        parsed_response = json.loads(function_response)

                        # Save the tool response
                        self.message_service.add_tool_message(message_id, function_response)
                        logging_utility.info(f"Tool response saved to thread: {thread_id}")

                        tool_results.append(parsed_response)  # Collect successful results
                    except Exception as func_e:
                        logging_utility.error(f"Error executing function '{function_name}': {str(func_e)}", exc_info=True)
                        # Do not append the result to tool_results if there's an error
                else:
                    raise ValueError(f"Function '{function_name}' is not available in available_functions")

        except Exception as e:
            logging_utility.error(f"Error in process_tool_calls: {str(e)}", exc_info=True)

        return tool_results  # Return collected results, excluding any that had errors

    def watson_generate_text(self, prompt, params):
        """
        Generates text using IBM Watson LLM.
        """
        try:
            # Set up generation parameters
            gen_parms = {
                WatsonGenParams.DECODING_METHOD: params.get('decoding_method', WatsonDecodingMethods.SAMPLE),
                WatsonGenParams.MAX_NEW_TOKENS: params.get('max_new_tokens', 100)
            }

            # Select the model ID
            model_id = self.watson_client.foundation_models.TextModels.LLAMA_3_2_90B_VISION_INSTRUCT

            # Initialize the model inference instance
            model = WatsonModelInference(
                model_id=model_id,
                credentials=self.watson_credentials,
                params=gen_parms,
                project_id=self.project_id,  # Pass the project_id from environment
                verify=False,
            )

            # Generate text
            generated_text_response = model.generate_text(prompt=prompt, params=gen_parms)
            return generated_text_response

        except Exception as e:
            logging_utility.error(f"Error in watson_generate_text: {str(e)}", exc_info=True)
            return ""

    def generate_final_response(self, thread_id, message_id, run_id, tool_results, messages, model):
        """
        Generates the final assistant response, incorporating tool results.
        """
        logging_utility.info(f"Generating final response for run_id: {run_id}")

        # Inject tool results into the conversation
        if tool_results:
            for result in tool_results:
                if result:
                    messages.append({'role': 'tool', 'content': json.dumps(result)})

        # Generate final response using updated messages
        full_response = ""

        if model == 'llama3.1':
            # Use local Ollama client for inference
            streaming_response = self.ollama_client.chat(
                model=model,
                messages=messages,
                options={'num_ctx': 4096},
                stream=True
            )

            for chunk in streaming_response:
                content = chunk['message']['content']

                # Check if the run has been cancelled during response generation
                current_run_status = self.run_service.retrieve_run(run_id=run_id).status
                if current_run_status in ["cancelling", "cancelled"]:
                    logging_utility.info(f"Run {run_id} is being cancelled or already cancelled, stopping response generation.")
                    break

                full_response += content
                yield content

        elif model == 'llama3.2:90b_v':
            # Use IBM Watson API for inference
            # Combine messages to form the prompt
            prompt_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in messages if msg['role'] != 'system'])

            # Generate text using IBM Watson
            generated_text = self.watson_generate_text(prompt_text, params={})

            # Simulate streaming by yielding chunks
            chunk_size = 100  # Adjust chunk size as needed
            for i in range(0, len(generated_text), chunk_size):
                chunk = generated_text[i:i+chunk_size]

                # Check if the run has been cancelled during response generation
                current_run_status = self.run_service.retrieve_run(run_id=run_id).status
                if current_run_status in ["cancelling", "cancelled"]:
                    logging_utility.info(f"Run {run_id} is being cancelled or already cancelled, stopping response generation.")
                    break

                full_response += chunk
                yield chunk

        else:
            logging_utility.error(f"Unsupported model: {model}")
            yield "Error: Unsupported model specified."

        # Finalize the run
        final_run_status = self.run_service.retrieve_run(run_id=run_id).status
        status_to_set = "completed" if final_run_status not in ["cancelling", "cancelled"] else "cancelled"

        self.message_service.save_assistant_message_chunk(thread_id, full_response, is_last_chunk=True)
        self.run_service.update_run_status(run_id, status_to_set)

        logging_utility.info(f"Run {run_id} marked as {status_to_set}")

    def process_conversation(self, thread_id, message_id, run_id, assistant_id, model='llama3.1'):
        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, model: %s",
            thread_id, run_id, model
        )

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info(
            "Retrieved assistant: id=%s, name=%s, model=%s",
            assistant.id, assistant.name, assistant.model
        )

        messages = self.message_service.get_formatted_messages(
            thread_id, system_message=assistant.instructions
        )
        logging_utility.debug("Original formatted messages: %s", messages)

        tool_filtering_messages = self.create_tool_filtering_messages(messages)
        tool_results = []

        # Initial chat or inference call based on model
        if model == 'llama3.1':
            response = self.ollama_client.chat(
                model=model,
                messages=tool_filtering_messages,
                options={'num_ctx': 4096},
                tools=self.tool_service.list_tools(assistant_id)
            )
            logging_utility.debug("Initial chat response: %s", response)

            if response['message'].get('tool_calls'):
                tool_results = self.process_tool_calls(
                    run_id, response['message']['tool_calls'], message_id, thread_id
                )

        elif model == 'llama3.2:90b_v':
            # For IBM Watson, we can process tool calls differently if needed
            # Currently, we'll proceed directly to generating the final response
            pass
        else:
            logging_utility.error(f"Unsupported model: {model}")
            return

        # Generate and stream the final response
        return self.generate_final_response(
            thread_id, message_id, run_id, tool_results, messages, model
        )


