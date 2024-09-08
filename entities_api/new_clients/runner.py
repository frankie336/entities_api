# new_clients/runner.py
import json
import os
from dotenv import load_dotenv
from entities_api.new_clients.assistant_client import AssistantService
from entities_api.new_clients.message_client import MessageService
from entities_api.new_clients.run_client import RunService
from entities_api.new_clients.thread_client import ThreadService
from entities_api.new_clients.user_client import UserService
from ollama import Client
from entities_api.services.logging_service import LoggingUtility

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()

# Simulates an API call to get flight times


def get_flight_times(departure: str, arrival: str) -> str:
    flights = {
        'NYC-LAX': {'departure': '08:00 AM', 'arrival': '11:30 AM', 'duration': '6h 30m'},
        'LAX-NYC': {'departure': '02:00 PM', 'arrival': '10:30 PM', 'duration': '5h 30m'},
        'LHR-JFK': {'departure': '10:00 AM', 'arrival': '01:00 PM', 'duration': '8h 00m'},
        'JFK-LHR': {'departure': '09:00 PM', 'arrival': '09:00 AM', 'duration': '7h 00m'},
        'CDG-DXB': {'departure': '11:00 AM', 'arrival': '08:00 PM', 'duration': '6h 00m'},
        'DXB-CDG': {'departure': '03:00 AM', 'arrival': '07:30 AM', 'duration': '7h 30m'},
    }
    key = f'{departure}-{arrival}'.upper()
    return json.dumps(flights.get(key, {'error': 'Flight not found'}))

class Runner:
    def __init__(self, base_url=os.getenv('ASSISTANTS_BASE_URL'), api_key='your api key'):
        self.base_url = base_url or os.getenv('ASSISTANTS_BASE_URL')
        self.api_key = api_key or os.getenv('API_KEY')
        self.user_service = UserService(self.base_url, self.api_key)
        self.assistant_service = AssistantService(self.base_url, self.api_key)
        self.thread_service = ThreadService(self.base_url, self.api_key)
        self.message_service = MessageService(self.base_url, self.api_key)
        self.run_service = RunService(self.base_url, self.api_key)
        self.ollama_client = Client()
        logging_utility.info("OllamaClient initialized with base_url: %s", self.base_url)

    def streamed_response_helper(self, messages, message_id, thread_id, run_id, model='llama3.1'):
        logging_utility.info("Starting streamed response for thread_id: %s, run_id: %s, model: %s", thread_id, run_id,
                             model)

        try:
            # Update the status to 'in_progress' as processing begins
            if not self.run_service.update_run_status(run_id, "in_progress"):
                logging_utility.error("Failed to update run status to in_progress for run_id: %s", run_id)
                return

            # First API call: Send the query and function description to the model
            response = self.ollama_client.chat(
                model=model,
                messages=messages,
                options={'num_ctx': 4096},
                tools=[
                    {
                        'type': 'function',
                        'function': {
                            'name': 'get_flight_times',
                            'description': 'Get the flight times between two cities',
                            'parameters': {
                                'type': 'object',
                                'properties': {
                                    'departure': {
                                        'type': 'string',
                                        'description': 'The departure city (airport code)',
                                    },
                                    'arrival': {
                                        'type': 'string',
                                        'description': 'The arrival city (airport code)',
                                    },
                                },
                                'required': ['departure', 'arrival'],
                            },
                        },
                    },

                    {
                        "type": "function",
                        "function": {
                            "name": "getAnnouncedPrefixes",
                            "description": "Retrieves the announced prefixes for a given ASN",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "resource": {
                                        "type": "string",
                                        "description": "The ASN for which to retrieve the announced prefixes"
                                    },
                                    "starttime": {
                                        "type": "string",
                                        "description": "The start time for the query (ISO8601 or Unix timestamp)"
                                    },
                                    "endtime": {
                                        "type": "string",
                                        "description": "The end time for the query (ISO8601 or Unix timestamp)"
                                    },
                                    "min_peers_seeing": {
                                        "type": "integer",
                                        "description": "Minimum number of RIS peers seeing the prefix for it to be included in the results"
                                    }
                                },
                                "required": ["resource"]
                            }
                        }
                    },

                ],
            )

            if response['message'].get('tool_calls'):
                logging_utility.info("Function call triggered for run_id: %s", response['message'].get('tool_calls'))
                # Process function calls made by the model
                available_functions = {
                    'get_flight_times': get_flight_times,
                }

                for tool in response['message'].get('tool_calls', []):
                    try:
                        function_name = tool['function']['name']
                        logging_utility.info("Calling function: %s for run_id: %s", function_name, run_id)
                        function_to_call = available_functions.get(function_name)
                        if function_to_call is None:
                            raise ValueError(f"Unknown function: {function_name}")

                        function_args = tool['function']['arguments']
                        if isinstance(function_args, str):
                            function_args = json.loads(function_args)
                        elif not isinstance(function_args, dict):
                            raise ValueError(f"Unexpected argument type: {type(function_args)}")

                        departure = function_args.get('departure')
                        arrival = function_args.get('arrival')
                        if not departure or not arrival:
                            raise ValueError("Missing required arguments: departure and arrival")

                        logging_utility.info("Function call arguments - departure: %s, arrival: %s", departure, arrival)
                        function_response = function_to_call(departure, arrival)
                        logging_utility.info("Function call response: %s", function_response)

                        self.message_service.add_tool_message(
                            message_id=message_id,
                            content=function_response
                        )

                        messages.append({
                            'role': 'tool',
                            'content': function_response,
                        })

                    except Exception as e:
                        logging_utility.error(f"Error processing function call: {str(e)}")
                        messages.append({
                            'role': 'tool',
                            'content': json.dumps({"error": f"Error processing function call: {str(e)}"}),
                        })
            else:
                logging_utility.info("No function call triggered for run_id: %s", run_id)

            # Stream the response, regardless of whether a tool call was made or not
            logging_utility.info("Starting streaming response for run_id: %s", run_id)
            streaming_response = self.ollama_client.chat(
                model=model,
                messages=messages,
                options={'num_ctx': 4096},
                stream=True
            )

            full_response = ""
            for chunk in streaming_response:
                # Check if the run has been cancelled
                current_run_status = self.run_service.retrieve_run(run_id=run_id).status
                if current_run_status in ["cancelling", "cancelled"]:
                    logging_utility.info("Run %s is being cancelled or already cancelled, stopping generation", run_id)
                    break

                content = chunk['message']['content']
                full_response += content
                logging_utility.debug("Received chunk: %s", content)
                yield content

            # After the loop, check the final status
            final_run_status = self.run_service.retrieve_run(run_id=run_id).status

            if final_run_status in ["cancelling", "cancelled"]:
                logging_utility.info("Run was cancelled during processing")
                status_to_set = "cancelled"
            else:
                logging_utility.info("Finished yielding all chunks")
                status_to_set = "completed"

            # Save the message (partial or complete)
            if not self.message_service.save_assistant_message_chunk(thread_id, full_response, is_last_chunk=True):
                logging_utility.error("Failed to save assistant message for thread_id: %s", thread_id)

            # Update the final run status
            if not self.run_service.update_run_status(run_id, status_to_set):
                logging_utility.error("Failed to update run status to %s for run_id: %s", status_to_set, run_id)

        except Exception as e:
            logging_utility.error("Error in streamed_response_helper: %s", str(e), exc_info=True)
            yield json.dumps({"error": "An error occurred while generating the response"})
            # Ensure run status is updated to failed in case of exception
            self.run_service.update_run_status(run_id, "failed")

        logging_utility.info("Exiting streamed_response_helper")


    def process_conversation(self, thread_id, message_id, run_id, assistant_id, model='llama3.1'):
        logging_utility.info("Processing conversation for thread_id: %s, run_id: %s, model: %s", thread_id, run_id, model)

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)

        logging_utility.info("Retrieved assistant: id=%s, name=%s, model=%s",
                             assistant.id, assistant.name, assistant.model)

        messages = self.message_service.get_formatted_messages(thread_id, system_message=assistant.instructions)
        logging_utility.debug("Formatted messages: %s", messages)
        return self.streamed_response_helper(messages, message_id, thread_id,  run_id, model)

