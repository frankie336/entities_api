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

    def process_tool_calls(self, run_id, tool_calls, message_id, thread_id):
        """
        Processes tool calls and waits for status to change to 'ready'.
        Returns the response of tool functions.
        """
        available_functions = {
            'get_flight_times': get_flight_times,
            'getAnnouncedPrefixes': getAnnouncedPrefixes,
        }

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
                if function_name in available_functions:
                    function_to_call = available_functions[function_name]
                    function_response = function_to_call(**function_args)
                    parsed_response = json.loads(function_response)

                    # Save the tool response
                    self.message_service.add_tool_message(message_id, function_response)
                    logging_utility.info(f"Tool response saved to thread: {thread_id}")

                    return parsed_response  # Return the result to be injected into final conversation

        except Exception as e:
            logging_utility.error(f"Error in process_tool_calls: {str(e)}", exc_info=True)

        return None  # Return None if the tool call fails or times out

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
        streaming_response = self.ollama_client.chat(
            model=model,
            messages=messages,
            options={'num_ctx': 4096},
            stream=True
        )

        full_response = ""
        for chunk in streaming_response:
            content = chunk['message']['content']
            full_response += content
            yield content

        # Finalize the run
        final_run_status = self.run_service.retrieve_run(run_id=run_id).status
        status_to_set = "completed" if final_run_status not in ["cancelling", "cancelled"] else "cancelled"

        self.message_service.save_assistant_message_chunk(thread_id, full_response, is_last_chunk=True)
        self.run_service.update_run_status(run_id, status_to_set)

        logging_utility.info(f"Run {run_id} marked as {status_to_set}")

    def process_conversation(self, thread_id, message_id, run_id, assistant_id, model='llama3.1'):
        logging_utility.info("Processing conversation for thread_id: %s, run_id: %s, model: %s", thread_id, run_id, model)

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        logging_utility.info("Retrieved assistant: id=%s, name=%s, model=%s", assistant.id, assistant.name, assistant.model)

        messages = self.message_service.get_formatted_messages(thread_id, system_message=assistant.instructions)
        logging_utility.debug("Original formatted messages: %s", messages)

        tool_filtering_messages = self.create_tool_filtering_messages(messages)
        tool_results = []

        # Initial chat call
        response = self.ollama_client.chat(
            model=model,
            messages=tool_filtering_messages,
            options={'num_ctx': 4096},
            tools=self.tool_service.list_tools(assistant_id)
        )
        logging_utility.debug("Initial chat response: %s", response)

        if response['message'].get('tool_calls'):
            tool_results.append(
                self.process_tool_calls(run_id, response['message']['tool_calls'], message_id, thread_id))

            from entities_api.new_clients.client import OllamaClient
            client = OllamaClient()

            check_interval = 1  # Check every second

            while True:
                pending_actions = self.action_service.get_actions_by_status(run_id=run_id, status='pending')
                logging_utility.info(f"Pending actions retrieved: {len(pending_actions)} for run_id: {run_id}")

                if pending_actions:
                    for action in pending_actions:
                        logging_utility.info(f"Pending action found: {action['id']}, attempting to update to 'ready'")


                        # Deal with function calls here
                        # We can use dependency injection
                        # to handle an aspect of function
                        # calling and tooling
                        def deal_with_tools():

                            update = client.actions_service.update_action(
                                action_id=action['id'],
                                status='ready'
                            )

                        deal_with_tools()



                if not pending_actions:
                    logging_utility.info(f"Tool call completed for run_id: {run_id}")
                    break  # Tool is ready

                logging_utility.info(
                    f"Pending actions still in progress for run_id: {run_id}. Retrying in {check_interval} seconds.")

                time.sleep(check_interval)

        # Generate and stream the final response
        return self.generate_final_response(thread_id, message_id, run_id, tool_results, messages, model)
