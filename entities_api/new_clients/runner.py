import json
import os
import time
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

    def wait_for_tool_call(self, run_id: str, timeout: int = 5, check_interval: int = 1):
        """
        Wait for the tool call to complete or timeout after a specified period.
        """
        logging_utility.info(f"Waiting for tool call status to change for run_id: {run_id}")

        elapsed_time = 0

        while elapsed_time < timeout:
            # Fetch the pending actions
            pending_actions = self.action_service.get_actions_by_status(run_id=run_id, status='pending')

            # If no pending actions, assume the tool call is complete
            if not pending_actions:
                logging_utility.info(f"Tool call completed for run_id: {run_id}")
                return True  # Status changed

            # Wait for the specified interval before checking again
            time.sleep(check_interval)
            elapsed_time += check_interval

        # Timeout case
        logging_utility.warning(f"Timeout reached for tool call status for run_id: {run_id}")
        return False  # Timeout occurred

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
            tools = self.tool_service.list_tools('asst_tOavLvJ3IosygwTfzdxfGf')
            logging_utility.info(f"Fetched {len(tools)} tools")

            # Initial chat response using tool filtering messages
            response = self.ollama_client.chat(model=model, messages=tool_filtering_messages, options={'num_ctx': 4096},
                                               tools=tools)
            logging_utility.debug("Initial chat response: %s", response)

            # If there are tool calls in the response
            if response['message'].get('tool_calls'):
                if not self.run_service.update_run_status(run_id, "requires_action"):
                    logging_utility.error(f"Failed to update run status to requires_action for run_id: {run_id}")

                for tool in response['message'].get('tool_calls', []):
                    function_name = tool['function']['name']
                    function_args = tool['function']['arguments']

                    logging_utility.info(f"Tool call triggered: {function_name}, args: {function_args}")

                    # Create an action for the tool call
                    action = self.action_service.create_action(tool_name=function_name, run_id=run_id,
                                                               function_args=function_args)
                    logging_utility.info(f"Action created: {action.id}")

                    # Wait for the tool call to complete or timeout
                    if self.wait_for_tool_call(run_id, timeout=60):
                        logging_utility.info(f"Tool call for run_id: {run_id} completed")
                    else:
                        logging_utility.warning(f"Tool call for run_id: {run_id} timed out")

            else:
                logging_utility.info("No tool calls in initial response")

            # Generate the final response and continue
            final_response = self.ollama_client.chat(model=model, messages=messages, options={'num_ctx': 4096},
                                                     stream=True)
            for chunk in final_response:
                yield chunk['message']['content']

        except Exception as e:
            logging_utility.error(f"Error during streamed response: {e}", exc_info=True)
            self.run_service.update_run_status(run_id, "failed")
            yield json.dumps({"error": "An error occurred while processing the tool call"})

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
