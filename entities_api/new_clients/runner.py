import json
import os
from dotenv import load_dotenv
from entities_api.new_clients.assistant_client import AssistantService
from entities_api.new_clients.message_client import MessageService
from entities_api.new_clients.run_client import RunService
from entities_api.new_clients.thread_client import ThreadService
from entities_api.new_clients.user_client import UserService
from entities_api.new_clients.tool_client import ClientToolService
from ollama import Client
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()

# Simulated API call to get flight times
def get_flight_times(departure: str, arrival: str) -> str:
    flights = {
        'NYC-LAX': {'departure': '08:00 AM', 'arrival': '11:30 AM', 'duration': '5h 30m'},
        'LAX-NYC': {'departure': '02:00 PM', 'arrival': '10:30 PM', 'duration': '5h 30m'},
        'LHR-JFK': {'departure': '10:00 AM', 'arrival': '01:00 PM', 'duration': '8h 00m'},
        'JFK-LHR': {'departure': '09:00 PM', 'arrival': '09:00 AM', 'duration': '7h 00m'},
        'CDG-DXB': {'departure': '11:00 AM', 'arrival': '08:00 PM', 'duration': '6h 00m'},
        'DXB-CDG': {'departure': '03:00 AM', 'arrival': '07:30 AM', 'duration': '7h 30m'},
    }

    key = f'{departure}-{arrival}'.upper()
    return json.dumps(flights.get(key, {'error': 'Flight not found'}))


class Runner:
    def __init__(self, base_url=os.getenv('ASSISTANTS_BASE_URL'), api_key=os.getenv('API_KEY')):
        self.base_url = base_url or os.getenv('ASSISTANTS_BASE_URL')
        self.api_key = api_key or os.getenv('API_KEY')
        self.user_service = UserService(self.base_url, self.api_key)
        self.assistant_service = AssistantService(self.base_url, self.api_key)
        self.thread_service = ThreadService(self.base_url, self.api_key)
        self.message_service = MessageService(self.base_url, self.api_key)
        self.run_service = RunService(self.base_url, self.api_key)
        self.ollama_client = Client()
        self.tool_service = ClientToolService(self.base_url, self.api_key)

        logging_utility.info("OllamaClient initialized with base_url: %s", self.base_url)

    def streamed_response_helper(self, messages, tools, thread_id, run_id, model='llama3.1'):
        logging_utility.info("Starting streamed response for thread_id: %s, run_id: %s, model: %s", thread_id, run_id, model)

        try:
            if not self.run_service.update_run_status(run_id, "in_progress"):
                logging_utility.error("Failed to update run status to in_progress for run_id: %s", run_id)
                return

            available_functions = {
                'get_flight_times': get_flight_times
            }

            response = self.ollama_client.chat(
                model=model,
                messages=messages,
                tools=tools,
                options={'num_ctx': 4096},
                stream=True
            )

            logging_utility.debug("This is the inbound tools: %s", tools)
            logging_utility.info("Response received from Ollama client")
            full_response = ""
            buffer = ""
            is_in_function_call = False
            accumulated_function_call = {}

            for chunk in response:
                current_run_status = self.run_service.retrieve_run(run_id=run_id).status
                if current_run_status in ["cancelling", "cancelled"]:
                    logging_utility.info("Run %s is being cancelled or already cancelled, stopping generation", run_id)
                    break

                # Log the raw chunk to understand its structure
                logging_utility.debug(f"Raw chunk: {chunk}")

                # If chunk is a dict, process accordingly (inspect the structure here)
                if isinstance(chunk, dict) and 'message' in chunk:
                    message_content = chunk['message'].get('content', '')
                    buffer += message_content

                    # Try to parse the chunk into JSON to detect if it's a valid tool call
                    try:
                        parsed_chunk = json.loads(buffer)

                        # Detect a tool call
                        if 'tool_calls' in parsed_chunk['message']:
                            is_in_function_call = True
                            accumulated_function_call.update(parsed_chunk['message']['tool_calls'])
                            logging_utility.debug(f"Accumulated response: {accumulated_function_call}")

                        # If we have a complete tool call
                        if is_in_function_call and 'parameters' in accumulated_function_call:
                            function_name = accumulated_function_call['name']
                            function_args = accumulated_function_call['parameters']

                            # If the tool call is complete, invoke the function
                            if function_name in available_functions:
                                logging_utility.debug(f"Invoking function: {function_name}")
                                function_response = available_functions[function_name](
                                    function_args['departure'],
                                    function_args['arrival']
                                )

                                logging_utility.debug(f"Function {function_name} response: {function_response}")
                                yield function_response

                                messages.append({'role': 'tool', 'content': function_response})
                                is_in_function_call = False
                                buffer = ""  # Clear buffer for next response
                                accumulated_function_call = {}

                    except json.JSONDecodeError:
                        # Keep buffering until we have a complete JSON
                        continue

                    # If no function call, stream normally
                    if not is_in_function_call:
                        full_response += buffer
                        buffer = ""  # Reset buffer after processing
                        yield message_content

                else:
                    # Handle other possible chunk types if they are not dictionaries
                    logging_utility.error(f"Unexpected chunk format: {chunk}")
                    yield json.dumps({"error": "Unexpected response format"})

            final_run_status = self.run_service.retrieve_run(run_id=run_id).status
            if final_run_status in ["cancelling", "cancelled"]:
                logging_utility.info("Run was cancelled during processing")
                status_to_set = "cancelled"
            else:
                logging_utility.info("Finished yielding all chunks")
                status_to_set = "completed"

            if not self.message_service.save_assistant_message_chunk(thread_id, full_response, is_last_chunk=True):
                logging_utility.error("Failed to save assistant message for thread_id: %s", thread_id)

            if not self.run_service.update_run_status(run_id, status_to_set):
                logging_utility.error("Failed to update run status to %s for run_id: %s", status_to_set, run_id)

        except Exception as e:
            logging_utility.error("Error in streamed_response_helper: %s", str(e), exc_info=True)
            yield json.dumps({"error": "An error occurred while generating the response"})
            self.run_service.update_run_status(run_id, "failed")

        logging_utility.info("Exiting streamed_response_helper")

    def process_conversation(self, thread_id, run_id, assistant_id, model='llama3.1'):
        logging_utility.info("Processing conversation for thread_id: %s, run_id: %s, model: %s", thread_id, run_id, model)

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info("Retrieved assistant: id=%s, name=%s, model=%s", assistant.id, assistant.name, assistant.model)

        messages = self.message_service.get_formatted_messages(thread_id, system_message=assistant.instructions)
        logging_utility.debug("Formatted messages: %s", messages)

        tools = self.tool_service.list_tools(assistant_id=assistant_id, restructure=True)
        logging_utility.debug("Restructured tools: %s", tools)

        return self.streamed_response_helper(messages, tools, thread_id, run_id, model)
