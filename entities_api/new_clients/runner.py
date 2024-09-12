import json
import os
import requests
from dotenv import load_dotenv
from entities_api.new_clients.assistant_client import AssistantService
from entities_api.new_clients.message_client import MessageService
from entities_api.new_clients.run_client import RunService
from entities_api.new_clients.thread_client import ThreadService
from entities_api.new_clients.user_client import UserService
from entities_api.new_clients.tool_client import ClientToolService
from entities_api.new_clients.actions_client import ClientActionService
from entities_api.schemas import ActionCreate
from ollama import Client
from entities_api.services.logging_service import LoggingUtility
from typing import Optional


# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


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


def getAnnouncedPrefixes(resource: str, starttime: Optional[str] = None, endtime: Optional[str] = None,
                         min_peers_seeing: int = 10) -> str:
    logging_utility.info('Retrieving announced prefixes for ASN: %s', resource)

    base_url = "https://stat.ripe.net/data/announced-prefixes/data.json"
    params = {
        "resource": resource,
        "starttime": starttime,
        "endtime": endtime,
        "min_peers_seeing": min_peers_seeing
    }

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        prefixes_data = response.json()

        if prefixes_data.get('status') == 'ok':
            response_text = "Announced Prefixes:\n\n"
            prefixes = prefixes_data.get('data', {}).get('prefixes', [])
            for prefix_data in prefixes:
                prefix = prefix_data.get('prefix', '')
                timelines = prefix_data.get('timelines', [])
                response_text += f"Prefix: {prefix}\n"
                response_text += "Timelines:\n"
                for timeline in timelines:
                    starttime = timeline.get('starttime', '')
                    endtime = timeline.get('endtime', '')
                    response_text += f"- Start: {starttime}, End: {endtime}\n"
                response_text += "\n"
            response_text += "---\n"
        else:
            logging_utility.warning('Failed to retrieve announced prefixes')
            response_text = "Failed to retrieve announced prefixes."

        return json.dumps({"result": response_text})

    except requests.RequestException as e:
        error_message = f"Error retrieving announced prefixes: {str(e)}"
        logging_utility.error(error_message)
        return json.dumps({"error": error_message})


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
        self.tool_service = ClientToolService(self.base_url, self.api_key)
        self.action_service = ClientActionService(self.base_url, self.api_key)

        logging_utility.info("OllamaClient initialized with base_url: %s", self.base_url)

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

    def streamed_response_helper(self, messages, tool_filtering_messages, message_id, thread_id, run_id,
                                 model='llama3.1'):
        logging_utility.info("Starting streamed response for thread_id: %s, run_id: %s, model: %s", thread_id, run_id,
                             model)
        logging_utility.debug("Original messages: %s", messages)
        logging_utility.debug("Tool filtering messages: %s", tool_filtering_messages)

        try:
            # Update run status to in_progress
            if not self.run_service.update_run_status(run_id, "in_progress"):
                logging_utility.error("Failed to update run status to in_progress for run_id: %s", run_id)
                return

            # Fetch tools for the assistant
            try:
                assistant_id = 'asst_lq88oYUTUG6u3VeEdPk8eb'  # Replace with dynamic assistant ID if needed

                tools = self.tool_service.list_tools(assistant_id)
                logging_utility.info("Fetched %d tools for assistant %s", len(tools), assistant_id)
            except Exception as e:
                logging_utility.error("Error fetching tools: %s", str(e))
                tools = []

            # Use tool_filtering_messages for the initial chat call
            response = self.ollama_client.chat(
                model=model,
                messages=tool_filtering_messages,
                options={'num_ctx': 4096},
                tools=tools,
            )
            logging_utility.debug("Initial chat response: %s", response)

            if response['message'].get('tool_calls'):
                # Update run status to requires_action
                if not self.run_service.update_run_status(run_id, "requires_action"):
                    logging_utility.error("Failed to update run status to requires_action for run_id: %s", run_id)

                logging_utility.info("Function call triggered for run_id: %s", run_id)

                available_functions = {
                    'get_flight_times': get_flight_times,
                    'getAnnouncedPrefixes': getAnnouncedPrefixes,
                }

                # Loop through the tool calls
                for tool in response['message'].get('tool_calls', []):
                    try:
                        function_name = tool['function']['name']
                        function_args = tool['function']['arguments']

                        logging_utility.info("Function call name for run_id: %s, function_name: %s", run_id,
                                             function_name)

                        # Look up tool ID based on the function name (tool_name)
                        tool_record = self.tool_service.get_tool_by_name(
                            function_name)  # Lookup the tool using its name

                        if not tool_record:
                            raise ValueError(f"Tool with name '{function_name}' not found")

                        tool_id = tool_record.id  # Use tool_id

                        # Tracking the state of triggered tools
                        action = self.action_service.create_action(
                            tool_name=function_name,
                            run_id=run_id,
                            function_args={"departure": "NYC", "arrival": "LAX"},

                        )
                        logging_utility.info("Created action for function call: %s", action.id)

                        update = self.action_service.update_action(
                            action_id=action.id,
                            status='pending'
                        )
                        logging_utility.info("Updated action status to 'pending' for action ID: %s",
                                             action.id)


                        # Process the function call
                        if function_name not in available_functions:
                            raise ValueError(f"Unknown function: {function_name}")

                        if isinstance(function_args, str):
                            function_args = json.loads(function_args)
                        elif not isinstance(function_args, dict):
                            raise ValueError(f"Unexpected argument type: {type(function_args)}")

                        # Execute the corresponding function
                        function_to_call = available_functions[function_name]
                        logging_utility.info("Executing function call: %s with args: %s", function_name, function_args)

                        function_response = function_to_call(**function_args)
                        logging_utility.debug("Function response: %s", function_response)

                        parsed_response = json.loads(function_response)

                        # Save the tool response
                        try:
                            tool_message = self.message_service.add_tool_message(message_id, function_response)
                            logging_utility.info("Saved tool response to thread: %s with tool message id: %s",
                                                 thread_id, tool_message.id)
                        except Exception as e:
                            logging_utility.error("Failed to save tool response: %s", str(e))

                        # Add non-error responses to the messages list
                        if 'error' not in parsed_response:
                            messages.append({'role': 'tool', 'content': function_response})
                            logging_utility.info("Added tool response to messages list")
                            logging_utility.debug("Updated messages: %s", messages)

                            # Update action status to "completed"
                            update = self.action_service.update_action(
                                action_id=action.id,
                                status='complete'
                            )

                            logging_utility.info("Updated action status to 'completed' for action ID: %s",
                                                 action.id)
                        else:
                            logging_utility.warning("Filtered out error response from %s: %s", function_name,
                                                    parsed_response['error'])


                            # Update action status to "failed"
                            update = self.action_service.update_action(
                                action_id=action.id,
                                status='failed'
                            )

                    except Exception as e:
                        error_message = f"Error executing function {function_name}: {str(e)}"
                        logging_utility.error(error_message, exc_info=True)

                        # Save the error message as a tool response
                        error_response = json.dumps({"error": error_message})
                        try:
                            tool_message = self.message_service.add_tool_message(message_id, error_response)
                            logging_utility.info("Saved error response to thread: %s with tool message id: %s",
                                                 thread_id, tool_message.id)
                        except Exception as save_error:
                            logging_utility.error("Failed to save error response: %s", str(save_error))

                        # Update action status to "failed" only if action_response exists
                        if 'action_response' in locals():
                            #self.action_service.update_action_status(action_response.id, status="failed",
                            pass                                          #result={"error": str(e)})
                        else:
                            logging_utility.error("Action could not be created, skipping status update")

            else:
                logging_utility.info("No function calls for run_id: %s", run_id)

            # Generate the final response using the updated messages (including non-error tool responses)
            logging_utility.info("Generating final response with updated message history")
            logging_utility.debug("Final messages for response generation: %s", messages)
            streaming_response = self.ollama_client.chat(
                model=model,
                messages=messages,  # Use the updated messages list
                options={'num_ctx': 4096},
                stream=True
            )

            full_response = ""
            for chunk in streaming_response:
                current_run_status = self.run_service.retrieve_run(run_id=run_id).status
                if current_run_status in ["cancelling", "cancelled"]:
                    logging_utility.info("Run %s is being cancelled or already cancelled, stopping generation", run_id)
                    break

                content = chunk['message']['content']
                full_response += content
                logging_utility.debug("Received chunk: %s", content)
                yield content

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

    def process_conversation(self, thread_id, message_id, run_id, assistant_id, model='llama3.1'):
        logging_utility.info("Processing conversation for thread_id: %s, run_id: %s, model: %s", thread_id, run_id,
                             model)

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)

        logging_utility.info("Retrieved assistant: id=%s, name=%s, model=%s",
                             assistant.id, assistant.name, assistant.model)

        messages = self.message_service.get_formatted_messages(thread_id, system_message=assistant.instructions)
        logging_utility.debug("Original formatted messages: %s", messages)

        # Create modified messages for tool filtering
        tool_filtering_messages = self.create_tool_filtering_messages(messages)
        logging_utility.debug("Modified messages for tool filtering: %s", tool_filtering_messages)

        return self.streamed_response_helper(messages, tool_filtering_messages, message_id, thread_id, run_id, model)