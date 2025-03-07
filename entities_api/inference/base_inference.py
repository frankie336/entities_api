import json
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from functools import lru_cache
from typing import List, Dict, Any

from together import Together

from entities_api.clients.client_actions_client import ClientActionService
from entities_api.clients.client_assistant_client import ClientAssistantService
from entities_api.clients.client_message_client import ClientMessageService
from entities_api.clients.client_run_client import ClientRunService
from entities_api.clients.client_thread_client import ThreadService
from entities_api.clients.client_tool_client import ClientToolService
from entities_api.clients.client_user_client import UserService
from entities_api.constants.assistant import WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS
from entities_api.constants.platform import MODEL_MAP
from entities_api.platform_tools.platform_tool_service import PlatformToolService
from entities_api.services.conversation_truncator import ConversationTruncator
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.vector_store_service import VectorStoreService

logging_utility = LoggingUtility()

class BaseInference(ABC):

    REASONING_PATTERN = re.compile(r'(<think>|</think>)')

    def __init__(self,
                 base_url=os.getenv('ASSISTANTS_BASE_URL'),
                 api_key=None,
                 assistant_id=None,
                 # New parameters for ConversationTruncator
                 model_name="deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
                 max_context_window=128000,
                 threshold_percentage=0.8,
                 available_functions=None):

        self.base_url = base_url
        self.api_key = api_key
        self.assistant_id = assistant_id
        self.available_functions = available_functions
        self._cancelled = False
        self._services = {}
        self.code_interpreter_response = False
        self.tool_response = None
        self.function_call = None
        self.client = Together(api_key=os.getenv("TOGETHER_API_KEY"))

        # Store truncation parameters
        self.truncator_params = {
            'model_name': model_name,
            'max_context_window': max_context_window,
            'threshold_percentage': threshold_percentage
        }

        logging_utility.info("BaseInference initialized with lazy service loading.")
        self.setup_services()

    def _get_service(self, service_class, custom_params=None):
        """Modified to handle PlatformToolService with assistant_id"""
        if service_class not in self._services:
            if service_class == PlatformToolService:
                # Special initialization for PlatformToolService
                if not self.get_assistant_id():
                    raise ValueError("PlatformToolService requires assistant_id")
                self._services[service_class] = service_class(
                    self.base_url,
                    self.api_key,
                    assistant_id=self.get_assistant_id()
                )
            elif service_class == ConversationTruncator:
                self._services[service_class] = service_class(
                    **self.truncator_params
                )
            else:
                params = custom_params or (self.base_url, self.api_key)
                self._services[service_class] = service_class(*params)

            logging_utility.info(f"Lazy-loaded {service_class.__name__}")
        return self._services[service_class]

    @property
    def user_service(self):
        return self._get_service(UserService)

    @property
    def assistant_service(self):
        return self._get_service(ClientAssistantService)

    @property
    def thread_service(self):
        return self._get_service(ThreadService)

    @property
    def message_service(self):
        return self._get_service(ClientMessageService)

    @property
    def run_service(self):
        return self._get_service(ClientRunService)

    @property
    def tool_service(self):
        return self._get_service(ClientToolService)

    @property
    def platform_tool_service(self):
        return self._get_service(PlatformToolService)

    @property
    def action_service(self):
        return self._get_service(ClientActionService)

    @property
    def vector_store_service(self):
        return self._get_service(VectorStoreService)

    @property
    def conversation_truncator(self):
        return self._get_service(ConversationTruncator)


    @abstractmethod
    def setup_services(self):
        """Initialize any additional services required by child classes."""
        pass

        # state

    def set_tool_response_state(self, value):
        self.tool_response = value

    def get_tool_response_state(self):
        return self.tool_response

    def set_function_call_state(self, value):
        self.function_call = value

    def get_function_call_state(self):
        return self.function_call

    @staticmethod
    def parse_code_interpreter_partial(text):

        """
        Parses a partial JSON-like string that begins with:
        {'name': 'code_interpreter', 'arguments': {'code':

        It captures everything following the 'code': marker.
        Note: Because the input is partial, the captured code may be incomplete.

        Returns:
            A dictionary with the key 'code' containing the extracted text,
            or None if no match is found.
        """
        pattern = re.compile(r"""
            \{\s*['"]name['"]\s*:\s*['"]code_interpreter['"]\s*,\s*   # "name": "code_interpreter"
            ['"]arguments['"]\s*:\s*\{\s*['"]code['"]\s*:\s*             # "arguments": {"code":
            (?P<code>.*)                                               # Capture the rest as code content
        """, re.VERBOSE | re.DOTALL)

        match = pattern.search(text)
        if match:
            return {'code': match.group('code').strip()}
        else:
            return None

    @staticmethod
    def parse_nested_function_call_json(text):
        """
        Parses a JSON-like string with a nested object structure and variable keys,
        supporting both single and double quotes, as well as multiline values.

        Expected pattern:
        {
            <quote>first_key<quote> : <quote>first_value<quote>,
            <quote>second_key<quote> : {
                <quote>nested_key<quote> : <quote>nested_value<quote>
            }
        }

        The regex uses named groups for the opening quote of each field and backreferences
        them to ensure the same type of quote is used to close the string.

        Returns a dictionary with the following keys if matched:
          - 'first_key'
          - 'first_value'
          - 'second_key'
          - 'nested_key'
          - 'nested_value'

        If no match is found, returns None.
        """
        pattern = re.compile(r'''
            \{\s*                                                      # Opening brace of outer object
            (?P<q1>["']) (?P<first_key> [^"']+?) (?P=q1) \s* : \s*      # First key
            (?P<q2>["']) (?P<first_value> [^"']+?) (?P=q2) \s* , \s*    # First value
            (?P<q3>["']) (?P<second_key> [^"']+?) (?P=q3) \s* : \s*     # Second key
            \{\s*                                                      # Opening brace of nested object
            (?P<q4>["']) (?P<nested_key> [^"']+?) (?P=q4) \s* : \s*     # Nested key
            (?P<q5>["']) (?P<nested_value> .*?) (?P=q5) \s*             # Nested value (multiline allowed)
            \} \s*                                                     # Closing brace of nested object
            \} \s*                                                     # Closing brace of outer object
        ''', re.VERBOSE | re.DOTALL)  # re.DOTALL allows matching multiline values

        match = pattern.search(text)
        if match:
            return {
                'first_key': match.group('first_key'),
                'first_value': match.group('first_value'),
                'second_key': match.group('second_key'),
                'nested_key': match.group('nested_key'),
                'nested_value': match.group('nested_value').strip(),  # Remove trailing whitespace
            }
        else:
            return None

    def convert_smart_quotes(self, text: str) -> str:

        replacements = {
            '‘': "'",  # smart single quote to standard single quote
            '’': "'",
            '“': '"',  # smart double quote to standard double quote
            '”': '"'
        }
        for smart, standard in replacements.items():
            text = text.replace(smart, standard)
        return text

    @staticmethod
    def is_valid_function_call_response(json_data: dict) -> bool:
        """
        Generalized validation that works for any tool while enforcing protocol rules.
        Doesn't validate specific parameter values, just ensures proper structure.
        """
        try:
            # Base structure check
            if not isinstance(json_data, dict):
                return False

            # Required top-level keys
            if {"name", "arguments"} - json_data.keys():
                return False

            # Name validation
            if not isinstance(json_data["name"], str) or not json_data["name"].strip():
                return False

            # Arguments validation
            if not isinstance(json_data["arguments"], dict):
                return False

            # Value type preservation check
            for key, value in json_data["arguments"].items():
                if not isinstance(key, str):
                    return False
                if isinstance(value, (list, dict)):
                    return False  # Prevent nested structures per guidelines

            return True

        except (TypeError, KeyError):
            return False

    def is_complex_vector_search(self, data: dict) -> bool:
        """Recursively validate operators with $ prefix"""
        for key, value in data.items():
            if key.startswith('$'):
                # Operator values can be primitives or nested structures
                if isinstance(value, dict) and not self.is_complex_vector_search(value):
                    return False
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and not self.is_complex_vector_search(item):
                            return False
            else:
                # Non-operator keys can have any value EXCEPT unvalidated dicts
                if isinstance(value, dict):
                    if not self.is_complex_vector_search(value):  # Recurse into nested dicts
                        return False
                elif isinstance(value, list):
                    return False  # Maintain original list prohibition

        return True


    def normalize_roles(self, conversation_history):
        """
        Normalize roles to ensure consistency with the Hyperbolic API.
        """
        normalized_history = []
        for message in conversation_history:
            role = message.get('role', '').strip().lower()
            if role not in ['user', 'assistant', 'system', 'tool', 'platform']:
                role = 'user'
            normalized_history.append({
                "role": role,
                "content": message.get('content', '').strip()
            })
        return normalized_history

    def extract_function_candidates(self, text):
        """
        Extracts potential JSON function call patterns from arbitrary text positions.
        Handles cases where function calls are embedded within other content.
        """
        # Regex pattern explanation:
        # - Looks for {...} structures with 'name' and 'arguments' keys
        # - Allows for nested JSON structures
        # - Tolerates some invalid JSON formatting that might appear in streams
        pattern = r'''
            \{                      # Opening curly brace
            \s*                     # Optional whitespace
            (["'])name\1\s*:\s*     # 'name' key with quotes
            (["'])(.*?)\2\s*,\s*    # Capture tool name
            (["'])arguments\4\s*:\s* # 'arguments' key
            (\{.*?\})               # Capture arguments object
            \s*\}                   # Closing curly brace
        '''

        candidates = []
        try:
            matches = re.finditer(pattern, text, re.DOTALL | re.VERBOSE)
            for match in matches:
                candidate = match.group(0)
                # Validate basic structure before adding
                if '"name"' in candidate and '"arguments"' in candidate:
                    candidates.append(candidate)
        except Exception as e:
            logging_utility.error(f"Candidate extraction error: {str(e)}")

        return candidates

    def extract_tool_invocations(self, text: str):
        """
        Extracts and validates all tool invocation patterns from unstructured text.
        Handles multi-line JSON and schema validation without recursive patterns.
        """
        # Remove markdown code fences (e.g., ```json ... ```)
        text = re.sub(r'```(?:json)?(.*?)```', r'\1', text, flags=re.DOTALL)

        # Normalization phase
        text = re.sub(r'[“”]', '"', text)
        text = re.sub(r'(\s|\\n)+', ' ', text)

        # Simplified pattern without recursion
        pattern = r'''
            \{         # Opening curly brace
            .*?        # Any characters
            "name"\s*:\s*"(?P<name>[^"]+)" 
            .*?        # Any characters
            "arguments"\s*:\s*\{(?P<args>.*?)\}
            .*?        # Any characters
            \}         # Closing curly brace
        '''

        tool_matches = []
        for match in re.finditer(pattern, text, re.DOTALL | re.VERBOSE):
            try:
                # Reconstruct with proper JSON formatting
                raw_json = match.group()
                parsed = json.loads(raw_json)

                # Schema validation
                if not all(key in parsed for key in ['name', 'arguments']):
                    continue
                if not isinstance(parsed['arguments'], dict):
                    continue

                tool_matches.append(parsed)
            except (json.JSONDecodeError, KeyError):
                continue

        return tool_matches


    def ensure_valid_json(self, text: str):


        """
        Ensures the accumulated tool response is in valid JSON format.
        - Fixes incorrect single quotes (`'`) → double quotes (`"`)
        - Ensures proper key formatting
        - Removes trailing commas if present
        """
        if not isinstance(text, str) or not text.strip():
            logging_utility.error("Received empty or non-string JSON content.")
            return None

        try:
            # Step 1: Standardize Quotes
            if "'" in text and '"' not in text:
                logging_utility.warning(f"Malformed JSON detected, attempting fix: {text}")
                text = text.replace("'", '"')

            # Step 2: Remove trailing commas (e.g., {"name": "web_search", "arguments": {"query": "test",},})
            text = re.sub(r",\s*}", "}", text)
            text = re.sub(r",\s*\]", "]", text)

            # Step 3: Validate JSON
            parsed_json = json.loads(text)  # Will raise JSONDecodeError if invalid
            return parsed_json  # Return corrected JSON object

        except json.JSONDecodeError as e:
            logging_utility.error(f"JSON decoding failed: {e} | Raw: {text}")
            return None  # Skip processing invalid JSON


    def normalize_content(self, content):
        """Smart format normalization with fallback"""
        try:
            return content if isinstance(content, dict) else \
                json.loads(self.ensure_valid_json(str(content)))
        except Exception as e:
            logging_utility.warning(f"Normalization failed: {str(e)}")
            return content  # Preserve for legacy handling

    def handle_error(self, assistant_reply, thread_id, assistant_id, run_id):
        """Handle errors and store partial assistant responses."""
        if assistant_reply:
            self.message_service.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply,
                role="assistant",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True
            )
            logging_utility.info("Partial assistant response stored successfully.")
            self.run_service.update_run_status(run_id, "failed")

    def finalize_conversation(self, assistant_reply, thread_id, assistant_id, run_id):
        """Finalize the conversation by storing the assistant's reply."""

        if assistant_reply:
            message = self.message_service.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply,
                role="assistant",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True
            )
            logging_utility.info("Assistant response stored successfully.")
            self.run_service.update_run_status(run_id, "completed")

            return message

    def get_vector_store_id_for_assistant(self, assistant_id: str, store_suffix: str = "chat") -> str:
        """
        Retrieve the vector store ID for a specific assistant and store suffix.

        Args:
            assistant_id (str): The ID of the assistant.
            store_suffix (str): The suffix of the vector store name (default: "chat").

        Returns:
            str: The collection name of the vector store.
        """
        # Retrieve a list of vector stores per assistant
        vector_stores = self.vector_store_service.get_vector_stores_for_assistant(assistant_id=assistant_id)

        # Map name to collection_name
        vector_store_mapping = {vs.name: vs.collection_name for vs in vector_stores}

        # Return the collection name for the specific store
        return vector_store_mapping[f"{assistant_id}-{store_suffix}"]



    def start_cancellation_listener(self, run_id: str, poll_interval: float = 1.0) -> None:
        """
        Starts a background thread to listen for cancellation events.
        Only starts if it hasn't already been started.
        """
        from entities_api.services.event_handler import EntitiesEventHandler

        if hasattr(self, "_cancellation_thread") and self._cancellation_thread.is_alive():
            logging_utility.info("Cancellation listener already running.")
            return

        def handle_event(event_type: str, event_data: Any):
            if event_type == "cancelled":
                return "cancelled"

        def listen_for_cancellation():
            event_handler = EntitiesEventHandler(
                run_service=self.run_service,
                action_service=self.action_service,
                event_callback=handle_event
            )
            while not self._cancelled:
                if event_handler._emit_event("cancelled", run_id) == "cancelled":
                    self._cancelled = True
                    logging_utility.info(f"Cancellation event detected for run {run_id}")
                    break
                time.sleep(poll_interval)

        self._cancellation_thread = threading.Thread(target=listen_for_cancellation, daemon=True)
        self._cancellation_thread.start()

    def check_cancellation_flag(self) -> bool:
        """Non-blocking check of the cancellation flag."""
        return self._cancelled


    def _process_tool_calls(self, thread_id,
                            assistant_id, content,
                            run_id):

        # Save the tool invocation for state management.
        self.action_service.create_action(
            tool_name=content["name"],
            run_id=run_id,
            function_args=content["arguments"]
        )

        # Update run status to 'action_required'
        self.run_service.update_run_status(run_id=run_id, new_status='action_required')
        logging_utility.info(f"Run {run_id} status updated to action_required")

        # Now wait for the run's status to change from 'action_required'.
        while True:
            run = self.run_service.retrieve_run(run_id)
            if run.status != "action_required":
                break
            time.sleep(1)

        logging_utility.info("Action status transition complete. Reprocessing conversation.")

        return content


    def _handle_web_search(self, thread_id, assistant_id, function_output, action):
        """Special handling for web search results."""
        try:

            search_output = str(function_output[0]) + WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS

            self._submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=search_output,
                action=action
            )
            logging_utility.info(
                "Web search results submitted for action %s",
                action.id
            )

        except IndexError as e:
            logging_utility.error(
                "Invalid web search output format for action %s: %s",
                action.id, str(e)
            )
            raise

    def _handle_code_interpreter(self, thread_id, assistant_id, function_output, action):
        """Special handling for code interpreter results."""
        try:
            parsed_output = json.loads(function_output)
            output_value = parsed_output['result']['output']

            self._submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=output_value,
                action=action
            )
            logging_utility.info(
                "Code interpreter output submitted for action %s",
                action.id
            )

        except json.JSONDecodeError as e:
            logging_utility.error(
                "Failed to parse code interpreter output for action %s: %s",
                action.id, str(e)
            )
            raise

    def _handle_vector_search(self, thread_id, assistant_id, function_output, action):
        """Special handling for web search results."""
        try:

            search_output = str(function_output)

            self._submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=search_output,
                action=action
            )
            logging_utility.info(
                "Web search results submitted for action %s",
                action.id
            )

        except IndexError as e:
            logging_utility.error(
                "Invalid web search output format for action %s: %s",
                action.id, str(e)
            )
            raise


    def set_assistant_id(self, assistant_id):
        self.assistant_id = assistant_id

    def get_assistant_id(self):
        return self.assistant_id

    def _process_platform_tool_calls(self, thread_id, assistant_id, content, run_id):
        """Process platform tool calls with enhanced logging and error handling."""

        self.set_assistant_id(assistant_id=assistant_id)

        try:
            logging_utility.info(
                "Starting tool call processing for run %s. Tool: %s",
                run_id, content["name"]
            )

            # Create action with sanitized logging
            action = self.action_service.create_action(
                tool_name=content["name"],
                run_id=run_id,
                function_args=content["arguments"]
            )

            logging_utility.debug(
                "Created action %s for tool %s",
                action.id, content["name"]
            )

            # Update run status
            self.run_service.update_run_status(run_id=run_id, new_status='action_required')
            logging_utility.info(
                "Run %s status updated to action_required for tool %s",
                run_id, content["name"]
            )

            # Execute tool call
            platform_tool_service = self.platform_tool_service

            function_output = platform_tool_service.call_function(
                function_name=content["name"],
                arguments=content["arguments"],

            )

            logging_utility.debug(
                "Tool %s executed successfully for run %s",
                content["name"], run_id
            )

            # Handle specific tool types
            tool_handlers = {
                "code_interpreter": self._handle_code_interpreter,
                "web_search": self._handle_web_search,
                "vector_store_search": self._handle_vector_search

            }

            handler = tool_handlers.get(content["name"])
            if handler:
                handler(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    function_output=function_output,
                    action=action
                )
            else:
                logging_utility.warning(
                    "No specific handler for tool %s, using default processing",
                    content["name"]
                )
                self._submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=function_output,
                    action=action
                )

        except Exception as e:
            logging_utility.error(
                "Failed to process tool call for run %s: %s",
                run_id, str(e), exc_info=True
            )
            self.action_service.update_action(action_id=action.id, status='failed')
            raise  # Re-raise for upstream handling


    def _submit_tool_output(self, thread_id, assistant_id, content, action):
        """Generic tool output submission with consistent logging."""

        try:
            self.message_service.submit_tool_output(
                thread_id=thread_id,
                content=content,
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy"
            )
            self.action_service.update_action(action_id=action.id, status='completed')
            logging_utility.debug(
                "Tool output submitted successfully for action %s",
                action.id
            )

        except Exception as e:
            logging_utility.error(
                "Failed to submit tool output for action %s: %s",
                action.id, str(e)
            )
            self.action_service.update_action(action_id=action.id, status='failed')
            raise

    def validate_and_set(self, content):
        """Core validation pipeline"""
        if self.is_valid_function_call_response(content):
            self.set_tool_response_state(True)
            self.set_function_call_state(content)
            return True
        return False

    def _get_model_map(self, value):
        """
        Front end model naming can clash with back end selection logic.
        This function is a mapper to resolve clashing names to unique values.
        """
        try:
            return MODEL_MAP[value]
        except KeyError:
            return False

    @abstractmethod
    def stream_response(self, thread_id, message_id, run_id, assistant_id,
                        model, stream_reasoning=False):
        """
        Streams tool responses in real time using the TogetherAI SDK.
        - Yields each token chunk immediately, split by reasoning tags.
        - Accumulates the full response for final validation.
        - Supports mid-stream cancellation.
        - Strips markdown triple backticks from the final accumulated content.
        - Excludes all characters prior to (and including) the partial code-interpreter match.
        """
        pass

    def stream_function_call_output(self, thread_id, run_id, assistant_id,
                                    model, stream_reasoning=False):

        """
        Simplified streaming handler for enforced tool response presentation.

        Forces assistant output formatting compliance through protocol-aware streaming:
        - Directly triggers tool output rendering from assistant's system instructions
        - Bypasses complex reasoning streams for direct tool response delivery
        - Maintains API compatibility with core streaming interface

        Protocol Enforcement:
        1. Injects protocol reminder message to assistant context
        2. Uses minimal temperature (0.6) for deterministic output
        3. Disables markdown wrapping in final output
        4. Maintains cancellation safety during tool output streaming

        Args:
            thread_id (str): UUID of active conversation thread
            run_id (str): Current execution run identifier
            assistant_id (str): Target assistant profile UUID
            model (str): Model identifier override for tool responses
            stream_reasoning (bool): [Reserved] Compatibility placeholder

        Yields:
            str: JSON-stringified chunks with structure:
                {'type': 'content'|'error', 'content': <payload>}

        Implementation Notes:
        - Bypasses complex message processing pipelines
        - Maintains separate cancellation listener instance
        - Enforces tool response protocol through system message injection
        - Accumulates raw content for final validation (JSON/format checks)
        """
        pass

    def _set_up_context_window(self, assistant_id, thread_id, trunk=True):
        """Prepares and optimizes conversation context for model processing.

        Constructs the conversation history while ensuring it fits within the model's
        context window limits through intelligent truncation. Combines multiple elements
        to create rich context:
        - Assistant's configured tools
        - Current instructions
        - Temporal awareness (today's date)
        - Complete conversation history

        Args:
            assistant_id (str): UUID of the assistant profile to retrieve tools/instructions
            thread_id (str): UUID of conversation thread for message history retrieval
            trunk (bool): Enable context window optimization via truncation (default: True)

        Returns:
            list: Processed message list containing either:
                - Truncated messages (if trunk=True)
                - Full normalized messages (if trunk=False)

        Processing Pipeline:
            1. Retrieve assistant configuration and tools
            2. Fetch complete conversation history
            3. Inject system message with:
               - Active tools list
               - Current instructions
               - Temporal context (today's date)
            4. Normalize message roles for API consistency
            5. Apply sliding window truncation when enabled

        Note:
            Uses LRU-cached service calls for assistant/message retrieval to optimize
            repeated requests with identical parameters.
        """
        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)
        tools = self.tool_service.list_tools(assistant_id=assistant_id, restructure=True)

        # Get the current date and time
        today = datetime.now()

        # Format the date and time as a string
        formatted_datetime = today.strftime("%Y-%m-%d %H:%M:%S")

        # Include the formatted date and time in the system message
        conversation_history = self.message_service.get_formatted_messages(
            thread_id,
            system_message="tools:" + str(
                tools) + "\n" + assistant.instructions + "\n" + f"Today's date and time:, {formatted_datetime}"
        )

        messages = self.normalize_roles(conversation_history)

        # Sliding Windows Truncation
        truncated_message = self.conversation_truncator.truncate(messages)

        if trunk:
            return truncated_message
        else:
            return messages


    @abstractmethod
    def process_conversation(self, thread_id, message_id, run_id, assistant_id,
                             model,  stream_reasoning=False):
        """Orchestrates conversation processing with real-time streaming and tool handling.

        Manages the complete lifecycle of assistant interactions including:
        - Streaming response generation
        - Function call detection and validation
        - Platform vs user tool execution
        - State management for tool responses
        - Conversation history preservation

        Args:
            thread_id (str): UUID of the conversation thread
            message_id (str): UUID of the initiating message
            run_id (str): UUID for tracking this execution instance
            assistant_id (str): UUID of the assistant profile
            model (str): Model identifier for response generation
            stream_reasoning (bool): Enable real-time reasoning stream

        Yields:
            dict: Streaming chunks with keys:
                - 'type': content/hot_code/error
                - 'content': chunk payload

        Process Flow:
            1. Stream initial LLM response
            2. Detect and validate function call candidates
            3. Process platform tools first (priority)
            4. Handle user-defined tools second
            5. Stream tool execution outputs
            6. Maintain conversation state throughout

        Maintains t ool response state through:
            - set_tool_response_state()
            - get_tool_response_state()
            - set_function_call_state()
            - get_function_call_state()
        """
        pass


    @lru_cache(maxsize=128)
    def cached_user_details(self, user_id):
        """Cache user details to avoid redundant API calls."""
        return self.user_service.get_user(user_id)

