import base64
import inspect
import json
import mimetypes
import os
import pprint
import re
import sys
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from functools import lru_cache
from typing import Any

import httpx
from openai import OpenAI
from projectdavid.clients.actions import ActionsClient
from projectdavid.clients.assistants import AssistantsClient
from projectdavid.clients.files import FileClient
from projectdavid.clients.messages import MessagesClient
from projectdavid.clients.runs import RunsClient
from projectdavid.clients.threads import ThreadsClient
from projectdavid.clients.tools import ToolsClient
from projectdavid.clients.vectors import VectorStoreClient
from projectdavid_common import ValidationInterface
from together import Together

from entities_api.constants.assistant import (
    CODE_ANALYSIS_TOOL_MESSAGE,
    CODE_INTERPRETER_MESSAGE,
    DEFAULT_REMINDER_MESSAGE,
    PLATFORM_TOOLS,
    WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS,
)
from entities_api.constants.platform import (
    ERROR_NO_CONTENT,
    MODEL_MAP,
    SPECIAL_CASE_TOOL_HANDLING,
)
from entities_api.platform_tools.code_interpreter.code_execution_client import (
    StreamOutput,
)
from entities_api.platform_tools.platform_tool_service import PlatformToolService
from entities_api.services.conversation_truncator import ConversationTruncator
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.user_service import UserService

logging_utility = LoggingUtility()
validator = ValidationInterface()


class MissingParameterError(ValueError):
    """Specialized error for missing service parameters"""


class ConfigurationError(RuntimeError):
    """Error for invalid service configurations"""


class AuthenticationError(PermissionError):
    """Error for credential-related issues"""


class BaseInference(ABC):

    REASONING_PATTERN = re.compile(r"(<think>|</think>)")

    def __init__(
        self,
        base_url=os.getenv("ASSISTANTS_BASE_URL"),
        api_key=None,
        assistant_id=None,
        thread_id=None,
        # New parameters for ConversationTruncator
        model_name="deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
        max_context_window=128000,
        threshold_percentage=0.8,
        available_functions=None,
    ):

        self.base_url = base_url
        self.api_key = api_key
        self.assistant_id = assistant_id
        self.thread_id = thread_id
        self.available_functions = available_functions
        self._cancelled = False
        self._services = {}
        self.code_interpreter_response = False
        self.tool_response = None
        self.function_call = None
        self.client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
        # -------------------------------
        # Clients
        # --------------------------------
        self.hyperbolic_client = OpenAI(
            api_key=os.getenv("HYPERBOLIC_API_KEY"),
            base_url="https://api.hyperbolic.xyz/v1",
            timeout=httpx.Timeout(30.0, read=30.0),
        )
        logging_utility.info("DeepSeekV3Cloud specific setup completed.")

        self.code_mode = False

        # Store truncation parameters
        self.truncator_params = {
            "model_name": model_name,
            "max_context_window": max_context_window,
            "threshold_percentage": threshold_percentage,
        }

        logging_utility.info("BaseInference initialized with lazy service loading.")
        self.setup_services()

    def _get_service(self, service_class, custom_params=None):
        """Intelligent service initializer with parametric awareness"""
        if service_class not in self._services:
            try:
                if service_class == PlatformToolService:
                    self._services[service_class] = self._init_platform_tool_service()
                elif service_class == ConversationTruncator:
                    self._services[service_class] = self._init_conversation_truncator()
                elif service_class == StreamOutput:
                    # Explicitly initialize StreamOutput with no args
                    self._services[service_class] = self._init_stream_output()
                else:
                    self._services[service_class] = self._init_general_service(
                        service_class, custom_params
                    )

                logging_utility.debug(f"Initialized {service_class.__name__}")
            except Exception as e:
                logging_utility.error(
                    f"Service init failed for {service_class.__name__}: {str(e)}"
                )
                raise
        return self._services[service_class]

    def _init_platform_tool_service(self):
        """Dedicated initializer for platform tools"""
        self._validate_platform_dependencies()
        return PlatformToolService(
            self.base_url,
            self.api_key,
            assistant_id=self.get_assistant_id(),
            thread_id=self.thread_id,
        )

    def _init_stream_output(self):
        return StreamOutput()

    def _init_conversation_truncator(self):
        """Config-driven truncator initialization"""
        return ConversationTruncator(**self.truncator_params)

    def _init_general_service(self, service_class, custom_params):
        """Parametric service initialization with signature analysis"""
        if custom_params is not None:
            return service_class(*custom_params)

        signature = inspect.signature(service_class.__init__)
        params = self._resolve_init_parameters(signature)
        return service_class(*params)

    @lru_cache(maxsize=32)
    def _resolve_init_parameters(self, signature):
        """Cached parameter resolution with attribute matching"""
        params = []
        for name, param in signature.parameters.items():
            if name == "self":
                continue
            if hasattr(self, name):
                params.append(getattr(self, name))
            elif param.default != inspect.Parameter.empty:
                params.append(param.default)
            else:
                raise MissingParameterError(f"Required parameter '{name}' not found")
        return params

    def _validate_platform_dependencies(self):
        """Centralized platform service validation"""
        if not self.get_assistant_id():
            raise ConfigurationError("Platform services require assistant_id")

        if not hasattr(self, "_platform_credentials_verified"):
            try:
                self._platform_credentials_verified = True
            except Exception as e:
                raise AuthenticationError(f"Credential validation failed: {str(e)}")

    @property
    def user_service(self):

        return self._get_service(UserService)

    @property
    def assistant_service(self):
        return self._get_service(AssistantsClient)

    @property
    def thread_service(self):
        return self._get_service(ThreadsClient)

    @property
    def message_service(self):
        return self._get_service(MessagesClient)

    @property
    def run_service(self):
        return self._get_service(RunsClient)

    @property
    def tool_service(self):
        return self._get_service(ToolsClient)

    @property
    def platform_tool_service(self):
        return self._get_service(PlatformToolService)

    @property
    def action_service(self):
        return self._get_service(ActionsClient)

    @property
    def code_execution_client(self):
        return self._get_service(StreamOutput)

    @property
    def vector_store_service(self):
        return self._get_service(VectorStoreClient)

    @property
    def files(self):
        return self._get_service(FileClient)

    @property
    def conversation_truncator(self):
        return self._get_service(ConversationTruncator)

    @abstractmethod
    def setup_services(self):
        """Initialize any additional services required by child classes."""
        pass

    # -------------------------------------------------
    # ENTITIES STATE INFORMATION
    # From time to time we need to pass
    # Some state information into PlatformToolService
    # This is the cleanest way to do that
    # -------------------------------------------------
    def set_assistant_id(self, assistant_id):
        if self.assistant_id != assistant_id:
            # Clear cached services that depend on assistant_id
            self._invalidate_service_cache(PlatformToolService)
            self.assistant_id = assistant_id

    def set_thread_id(self, thread_id):
        if self.thread_id != thread_id:
            # Clear cached services that depend on thread_id
            self._invalidate_service_cache(PlatformToolService)
            self.thread_id = thread_id

    def get_assistant_id(self):
        return self.assistant_id

    def get_thread_id(self):
        return self.assistant_id

    def _invalidate_service_cache(self, service_class):
        """Remove a specific service from the cache"""
        if service_class in self._services:
            del self._services[service_class]
            logging_utility.debug(f"Invalidated cache for {service_class.__name__}")

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
        pattern = re.compile(
            r"""
            \{\s*['"]name['"]\s*:\s*['"]code_interpreter['"]\s*,\s*   # "name": "code_interpreter"
            ['"]arguments['"]\s*:\s*\{\s*['"]code['"]\s*:\s*             # "arguments": {"code":
            (?P<code>.*)                                               # Capture the rest as code content
        """,
            re.VERBOSE | re.DOTALL,
        )

        match = pattern.search(text)
        if match:
            return {"code": match.group("code").strip()}
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
        pattern = re.compile(
            r"""
            \{\s*                                                      # Opening brace of outer object
            (?P<q1>["']) (?P<first_key> [^"']+?) (?P=q1) \s* : \s*      # First key
            (?P<q2>["']) (?P<first_value> [^"']+?) (?P=q2) \s* , \s*    # First value
            (?P<q3>["']) (?P<second_key> [^"']+?) (?P=q3) \s* : \s*     # Second key
            \{\s*                                                      # Opening brace of nested object
            (?P<q4>["']) (?P<nested_key> [^"']+?) (?P=q4) \s* : \s*     # Nested key
            (?P<q5>["']) (?P<nested_value> .*?) (?P=q5) \s*             # Nested value (multiline allowed)
            } \s*                                                     # Closing brace of nested object
            } \s*                                                     # Closing brace of outer object
        """,
            re.VERBOSE | re.DOTALL,
        )  # re.DOTALL allows matching multiline values

        match = pattern.search(text)
        if match:
            return {
                "first_key": match.group("first_key"),
                "first_value": match.group("first_value"),
                "second_key": match.group("second_key"),
                "nested_key": match.group("nested_key"),
                "nested_value": match.group(
                    "nested_value"
                ).strip(),  # Remove trailing whitespace
            }
        else:
            return None

    def convert_smart_quotes(self, text: str) -> str:

        replacements = {
            "‘": "'",  # smart single quote to standard single quote
            "’": "'",
            "“": '"',  # smart double quote to standard double quote
            "”": '"',
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
            if key.startswith("$"):
                # Operator values can be primitives or nested structures
                if isinstance(value, dict) and not self.is_complex_vector_search(value):
                    return False
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and not self.is_complex_vector_search(
                            item
                        ):
                            return False
            else:
                # Non-operator keys can have any value EXCEPT unvalidated dicts
                if isinstance(value, dict):
                    if not self.is_complex_vector_search(
                        value
                    ):  # Recurse into nested dicts
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
            role = message.get("role", "").strip().lower()
            if role not in ["user", "assistant", "system", "tool", "platform"]:
                role = "user"
            normalized_history.append(
                {"role": role, "content": message.get("content", "").strip()}
            )
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
        pattern = r"""
            \{                      # Opening curly brace
            \s*                     # Optional whitespace
            (["'])name\1\s*:\s*     # 'name' key with quotes
            (["'])(.*?)\2\s*,\s*    # Capture tool name
            (["'])arguments\4\s*:\s* # 'arguments' key
            (\{.*?\})               # Capture arguments object
            \s*\}                   # Closing curly brace
        """

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

    def extract_function_calls_within_body_of_text(self, text: str):
        """
        Extracts and validates all tool invocation patterns from unstructured text.
        Handles multi-line JSON and schema validation without recursive patterns.
        """
        # Remove markdown code fences (e.g., ```json ... ```)
        text = re.sub(r"```(?:json)?(.*?)```", r"\1", text, flags=re.DOTALL)

        # Normalization phase
        text = re.sub(r"[“”]", '"', text)
        text = re.sub(r"(\s|\\n)+", " ", text)

        # Simplified pattern without recursion
        pattern = r"""
            \{         # Opening curly brace
            .*?        # Any characters
            "name"\s*:\s*"(?P<name>[^"]+)"
            .*?        # Any characters
            "arguments"\s*:\s*\{(?P<args>.*?)\}
            .*?        # Any characters
            \}         # Closing curly brace
        """

        tool_matches = []
        for match in re.finditer(pattern, text, re.DOTALL | re.VERBOSE):
            try:
                # Reconstruct with proper JSON formatting
                raw_json = match.group()
                parsed = json.loads(raw_json)

                # Schema validation
                if not all(key in parsed for key in ["name", "arguments"]):
                    continue
                if not isinstance(parsed["arguments"], dict):
                    continue

                tool_matches.append(parsed)
            except (json.JSONDecodeError, KeyError):
                continue

        return tool_matches

    def ensure_valid_json(self, text: str):
        """
        Ensures the input text represents a valid JSON dictionary.
        Handles:
        - Direct JSON parsing.
        - JSON strings that are escaped within an outer string (e.g., '"{\"key\": \"value\"}"').
        - Incorrect single quotes (`'`) -> double quotes (`"`).
        - Trailing commas before closing braces/brackets.

        Returns a parsed JSON dictionary if successful, otherwise returns False.
        """
        global fixed_text
        if not isinstance(text, str) or not text.strip():
            logging_utility.error(
                "Received empty or non-string content for JSON validation."
            )
            return False

        original_text_for_logging = text[:200] + (
            "..." if len(text) > 200 else ""
        )  # Log snippet
        processed_text = text.strip()
        parsed_json = None

        # --- Stage 1: Attempt Direct or Unescaping Parse ---
        try:
            # Attempt parsing directly. This might succeed if the input is already valid JSON,
            # OR if it's an escaped JSON string like "\"{\\\"key\\\": \\\"value\\\"}\"".
            # In the latter case, json.loads() will return the *inner* string "{\"key\": \"value\"}".
            intermediate_parse = json.loads(processed_text)

            if isinstance(intermediate_parse, dict):
                # Direct parse successful and it's a dictionary!
                logging_utility.debug("Direct JSON parse successful.")
                parsed_json = intermediate_parse
                # We can return early if we don't suspect trailing commas in this clean case
                # Let's apply comma fix just in case, doesn't hurt.
                # Fall through to Stage 2 for potential comma fixing.

            elif isinstance(intermediate_parse, str):
                # Parsed successfully, but resulted in a string.
                # This means the original 'processed_text' was an escaped JSON string.
                # 'intermediate_parse' now holds the actual JSON string we need to parse.
                logging_utility.warning(
                    "Initial parse resulted in string, attempting inner JSON parse."
                )
                processed_text = (
                    intermediate_parse  # Use the unescaped string for the next stage
                )
                # Fall through to Stage 2 for parsing and fixes

            else:
                # Parsed to something other than dict or string (e.g., list, number)
                logging_utility.error(
                    f"Direct JSON parse resulted in unexpected type: {type(intermediate_parse)}. Expected dict or escaped string."
                )
                return False  # Not suitable for function call structure

        except json.JSONDecodeError:
            # Direct parse failed. This is expected if it needs quote/comma fixes,
            # or if it wasn't an escaped string to begin with.
            logging_utility.debug(
                "Direct/Unescaping parse failed. Proceeding to fixes."
            )
            # Fall through to Stage 2 where 'processed_text' is still the original stripped text.
            pass  # Continue to Stage 2
        except Exception as e:
            # Catch unexpected errors during the first parse attempt
            logging_utility.error(
                f"Unexpected error during initial JSON parse stage: {e}. Text: {original_text_for_logging}",
                exc_info=True,
            )
            return False

        # --- Stage 2: Apply Fixes and Attempt Final Parse ---
        # This stage runs if:
        # 1. Direct parse succeeded yielding a dict (parsed_json is set) -> mainly for comma fix.
        # 2. Direct parse yielded a string (processed_text updated) -> needs parsing + fixes.
        # 3. Direct parse failed (processed_text is original) -> needs parsing + fixes.

        if parsed_json and isinstance(parsed_json, dict):
            # If already parsed to dict, just check for/fix trailing commas in string representation
            # This is less common, usually fix before parsing. Let's skip for simplicity unless needed.
            logging_utility.debug(
                "JSON already parsed, skipping fix stage (commas assumed handled or valid)."
            )
            # If trailing commas *after* initial parse are a problem, convert dict back to string, fix, re-parse (complex).
            # Let's assume the initial parse handled it or it was valid.
            pass  # proceed to return parsed_json
        else:
            # We need to parse 'processed_text' (either original or unescaped string) after fixes
            try:
                # Fix 1: Standardize Single Quotes (Use cautiously)
                # Only apply if single quotes are present and double quotes are likely not intentional structure
                # This is heuristic and might break valid JSON with single quotes in string values.
                if "'" in processed_text and '"' not in processed_text.replace(
                    "\\'", ""
                ):  # Avoid replacing escaped quotes if possible
                    logging_utility.warning(
                        f"Attempting single quote fix on: {processed_text[:100]}..."
                    )
                    fixed_text = processed_text.replace("'", '"')
                else:
                    fixed_text = processed_text  # No quote fix needed or too risky

                # Fix 2: Remove Trailing Commas (before closing brace/bracket)
                # Handles cases like [1, 2,], {"a":1, "b":2,}
                fixed_text = re.sub(r",(\s*[}\]])", r"\1", fixed_text)

                # Final Parse Attempt
                parsed_json = json.loads(fixed_text)

                if not isinstance(parsed_json, dict):
                    logging_utility.error(
                        f"Parsed JSON after fixes is not a dictionary (type: {type(parsed_json)}). Text after fixes: {fixed_text[:200]}..."
                    )
                    return False

                logging_utility.info("JSON successfully parsed after fixes.")

            except json.JSONDecodeError as e:
                logging_utility.error(
                    f"Failed to parse JSON even after fixes. Error: {e}. Text after fixes attempt: {fixed_text[:200]}..."
                )
                return False
            except Exception as e:
                logging_utility.error(
                    f"Unexpected error during JSON fixing/parsing stage: {e}. Text: {original_text_for_logging}",
                    exc_info=True,
                )
                return False

        # --- Stage 3: Final Check and Return ---
        if isinstance(parsed_json, dict):
            return parsed_json
        else:
            # Should technically be caught earlier, but as a safeguard
            logging_utility.error(
                "Final check failed: parsed_json is not a dictionary."
            )
            return False

    def normalize_content(self, content):
        """Smart format normalization with fallback."""
        try:
            # If already a dictionary, use it as-is; otherwise, try to parse the JSON
            if isinstance(content, dict):
                return content
            else:
                validated = self.ensure_valid_json(str(content))
                # If validation fails (i.e. returns False), then we simply return False
                return validated if validated is not False else False
        except Exception as e:
            logging_utility.warning(f"Normalization failed: {str(e)}")
            return content  # Preserve for legacy handling if needed

    def handle_error(self, assistant_reply, thread_id, assistant_id, run_id):
        """Handle errors and store partial assistant responses."""
        if assistant_reply:
            self.message_service.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply,
                role="assistant",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True,
            )
            logging_utility.info("Partial assistant response stored successfully.")
            self.run_service.update_run_status(run_id, validator.StatusEnum.failed)

    def finalize_conversation(self, assistant_reply, thread_id, assistant_id, run_id):
        """Finalize the conversation by storing the assistant's reply."""

        if assistant_reply:
            message = self.message_service.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply,
                role="assistant",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True,
            )

            logging_utility.info("Assistant response stored successfully.")

            self.run_service.update_run_status(run_id, validator.StatusEnum.completed)

            return message

    def get_vector_store_id_for_assistant(
        self, assistant_id: str, store_suffix: str = "chat"
    ) -> str:
        """
        Retrieve the vector store ID for a specific assistant and store suffix.

        Args:
            assistant_id (str): The ID of the assistant.
            store_suffix (str): The suffix of the vector store name (default: "chat").

        Returns:
            str: The collection name of the vector store.
        """
        # Retrieve a list of vector stores per assistant
        vector_stores = self.vector_store_service.get_vector_stores_for_assistant(
            assistant_id=assistant_id
        )

        # Map name to collection_name
        vector_store_mapping = {vs.name: vs.collection_name for vs in vector_stores}

        # Return the collection name for the specific store
        return vector_store_mapping[f"{assistant_id}-{store_suffix}"]

    def start_cancellation_listener(
        self, run_id: str, poll_interval: float = 1.0
    ) -> None:
        """
        Starts a background thread to listen for cancellation events.
        Only starts if it hasn't already been started.
        """
        from entities_api.services.event_handler import EntitiesEventHandler

        if (
            hasattr(self, "_cancellation_thread")
            and self._cancellation_thread.is_alive()
        ):
            logging_utility.info("Cancellation listener already running.")
            return

        def handle_event(event_type: str, event_data: Any):
            if event_type == "cancelled":
                return "cancelled"

        def listen_for_cancellation():
            event_handler = EntitiesEventHandler(
                run_service=self.run_service,
                action_service=self.action_service,
                event_callback=handle_event,
            )
            while not self._cancelled:
                if event_handler._emit_event("cancelled", run_id) == "cancelled":
                    self._cancelled = True
                    logging_utility.info(
                        f"Cancellation event detected for run {run_id}"
                    )
                    break
                time.sleep(poll_interval)

        self._cancellation_thread = threading.Thread(
            target=listen_for_cancellation, daemon=True
        )
        self._cancellation_thread.start()

    def check_cancellation_flag(self) -> bool:
        """Non-blocking check of the cancellation flag."""
        return self._cancelled

    def _process_tool_calls(self, thread_id, assistant_id, content, run_id):

        # Save the tool invocation for state management.
        self.action_service.create_action(
            tool_name=content["name"], run_id=run_id, function_args=content["arguments"]
        )

        # Update run status to 'action_required'
        self.run_service.update_run_status(
            run_id=run_id, new_status=validator.StatusEnum.pending_action
        )
        logging_utility.info(f"Run {run_id} status updated to action_required")

        # Now wait for the run's status to change from 'action_required'.
        while True:
            run = self.run_service.retrieve_run(run_id)
            if run.status != "action_required":
                break
            time.sleep(1)

        logging_utility.info(
            "Action status transition complete. Reprocessing conversation."
        )

        return content

    def _handle_web_search(self, thread_id, assistant_id, function_output, action):
        """Special handling for web search results."""
        try:

            search_output = (
                str(function_output[0]) + WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS
            )

            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=search_output,
                action=action,
            )
            logging_utility.info(
                "Web search results submitted for action %s", action.id
            )

        except IndexError as e:
            logging_utility.error(
                "Invalid web search output format for action %s: %s", action.id, str(e)
            )
            raise

    def _handle_code_interpreter(
        self, thread_id, assistant_id, function_output, action
    ):
        """Special handling for code interpreter results."""
        try:
            parsed_output = json.loads(function_output)
            output_value = parsed_output["result"]["output"]

            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=output_value,
                action=action,
            )
            logging_utility.info(
                "Code interpreter output submitted for action %s", action.id
            )

        except json.JSONDecodeError as e:
            logging_utility.error(
                "Failed to parse code interpreter output for action %s: %s",
                action.id,
                str(e),
            )
            raise

    def _handle_vector_search(self, thread_id, assistant_id, function_output, action):
        """Special handling for web search results."""
        try:

            search_output = str(function_output)

            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=search_output,
                action=action,
            )
            logging_utility.info(
                "Web search results submitted for action %s", action.id
            )

        except IndexError as e:
            logging_utility.error(
                "Invalid web search output format for action %s: %s", action.id, str(e)
            )
            raise

    def _handle_computer(self, thread_id, assistant_id, function_output, action):
        """Special handling for web search results."""
        try:

            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=function_output,
                action=action,
            )
            logging_utility.info(
                "Web search results submitted for action %s", action.id
            )

        except IndexError as e:
            logging_utility.error(
                "Invalid web search output format for action %s: %s", action.id, str(e)
            )
            raise

    def _submit_code_interpreter_output(self, thread_id, assistant_id, content, action):
        """special case code interpreter output submission"""

        try:
            self.message_service.submit_tool_output(
                thread_id=thread_id,
                content=content,
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy",
            )
            self.action_service.update_action(action_id=action.id, status="completed")
            logging_utility.debug(
                "Tool output submitted successfully for action %s", action.id
            )

        except Exception as e:
            logging_utility.error(
                "Failed to submit tool output for action %s: %s", action.id, str(e)
            )
            self.action_service.update_action(action_id=action.id, status="failed")
            raise

    def _process_platform_tool_calls(self, thread_id, assistant_id, content, run_id):
        """Process platform tool calls with enhanced logging and error handling."""

        self.set_assistant_id(assistant_id=assistant_id)
        self.set_thread_id(thread_id=thread_id)

        try:
            logging_utility.info(
                "Starting tool call processing for run %s. Tool: %s",
                run_id,
                content["name"],
            )

            # Create action with sanitized logging
            action = self.action_service.create_action(
                tool_name=content["name"],
                run_id=run_id,
                function_args=content["arguments"],
            )

            logging_utility.debug(
                "Created action %s for tool %s", action.id, content["name"]
            )

            # Update run status
            self.run_service.update_run_status(
                run_id=run_id, new_status=validator.StatusEnum.pending_action
            )
            logging_utility.info(
                "Run %s status updated to action_required for tool %s",
                run_id,
                content["name"],
            )

            # Execute tool call
            platform_tool_service = self.platform_tool_service

            function_output = platform_tool_service.call_function(
                function_name=content["name"],
                arguments=content["arguments"],
            )

            logging_utility.debug(
                "Tool %s executed successfully for run %s", content["name"], run_id
            )

            # Handle specific tool types
            tool_handlers = {
                "code_interpreter": self._handle_code_interpreter,
                "web_search": self._handle_web_search,
                "vector_store_search": self._handle_vector_search,
                "computer": self._handle_computer,
            }

            handler = tool_handlers.get(content["name"])
            if handler:
                handler(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    function_output=function_output,
                    action=action,
                )
            else:
                logging_utility.warning(
                    "No specific handler for tool %s, using default processing",
                    content["name"],
                )
                self._submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=function_output,
                    action=action,
                )

        except Exception as e:
            logging_utility.error(
                "Failed to process tool call for run %s: %s",
                run_id,
                str(e),
                exc_info=True,
            )
            self.action_service.update_action(action_id=action.id, status="failed")
            raise  # Re-raise for upstream handling

    def submit_tool_output(self, thread_id, content, assistant_id, action):
        """
        Submits tool output and updates the action status.
        Raises exceptions if any occur and sends the error output to the user.
        """
        if not content:
            content = ERROR_NO_CONTENT
            logging_utility.error("No content returned for action %s", action.id)

        try:
            # Submit tool output
            self.message_service.submit_tool_output(
                thread_id=thread_id,
                content=content,
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy",  # Replace with actual tool_id if available
            )

            # Update action status
            self.action_service.update_action(action_id=action.id, status="completed")
            logging_utility.debug(
                "Tool output submitted successfully for action %s", action.id
            )
        except Exception as e:
            # Log the error
            logging_utility.error(
                "Failed to submit tool output for action %s: %s", action.id, str(e)
            )

            # Send the error message to the user
            self.message_service.submit_tool_output(
                thread_id=thread_id,
                content=f"ERROR: {str(e)}",
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy",  # Replace with actual tool_id if available
            )

            # Update action status to 'failed'
            self.action_service.update_action(action_id=action.id, status="failed")

            # Re-raise the exception for further handling
            raise

    def handle_code_interpreter_action(
        self, thread_id, run_id, assistant_id, arguments_dict
    ):

        action = self.action_service.create_action(
            tool_name="code_interpreter", run_id=run_id, function_args=arguments_dict
        )

        code = arguments_dict.get("code")
        uploaded_files = (
            []
        )  # This list will still contain the original (potentially wrong) mime_type from Step 1
        hot_code_buffer = []
        final_content_for_assistant = ""  # Initialize variable for Step 6

        # -------------------------------
        # Step 1: Stream raw code execution output as-is
        # -------------------------------
        logging_utility.info("Starting code execution streaming...")
        try:
            # Use a temporary list to hold chunks received during execution
            execution_chunks = []
            for chunk_str in self.code_execution_client.stream_output(code):
                execution_chunks.append(chunk_str)  # Store raw chunks first

            # Now process the stored chunks
            for chunk_str in execution_chunks:
                try:
                    parsed_chunk_wrapper = json.loads(chunk_str)
                    # --- Crucial: Adapt based on actual structure from stream_output ---
                    # Check if the structure is { "stream_type": "...", "chunk": {...} }
                    if (
                        "stream_type" in parsed_chunk_wrapper
                        and "chunk" in parsed_chunk_wrapper
                    ):
                        parsed = parsed_chunk_wrapper["chunk"]
                        # Yield the original wrapper structure
                        yield chunk_str  # Yield the raw JSON string as received
                    else:
                        # Assume the old structure if the new one isn't found
                        parsed = parsed_chunk_wrapper
                        # Wrap in the expected frontend structure before yielding
                        yield json.dumps(
                            {"stream_type": "code_execution", "chunk": parsed}
                        )

                    # Process the parsed content (the actual chunk data)
                    chunk_type = parsed.get("type")
                    content = parsed.get("content")

                    if chunk_type == "status":
                        status_content = content  # Renamed for clarity
                        logging_utility.debug(
                            "Received status chunk: %s", status_content
                        )
                        if status_content == "complete" and "uploaded_files" in parsed:
                            # Extract uploaded files metadata - this list has the original mime_type
                            uploaded_files_metadata = parsed.get("uploaded_files", [])
                            uploaded_files.extend(uploaded_files_metadata)
                            logging_utility.info(
                                "Execution complete. Received uploaded files metadata: %s",
                                uploaded_files_metadata,
                            )
                        elif status_content == "process_complete":
                            logging_utility.info(
                                "Code execution process completed with exit code: %s",
                                parsed.get("exit_code"),
                            )

                        # Append status to buffer *only if* needed for final output
                        # hot_code_buffer.append(f"[{status_content}]") # Often not needed in final output

                    elif chunk_type == "hot_code_output":
                        # Append actual code output
                        hot_code_buffer.append(content)
                    elif chunk_type == "error":
                        logging_utility.error(
                            "Received error chunk during code execution: %s", content
                        )
                        hot_code_buffer.append(f"[Code Execution Error: {content}]")
                    # Ignore other types like 'hot_code' for the buffer meant for final output

                except json.JSONDecodeError:
                    logging_utility.error("Failed to decode JSON chunk: %s", chunk_str)
                    # Decide how to handle invalid JSON - maybe yield an error chunk?
                    yield json.dumps(
                        {
                            "stream_type": "code_execution",
                            "chunk": {
                                "type": "error",
                                "content": "Received invalid data from code execution.",
                            },
                        }
                    )
                except Exception as e:
                    logging_utility.error(
                        "Error processing execution chunk: %s - Chunk: %s",
                        str(e),
                        chunk_str,
                        exc_info=True,
                    )
                    yield json.dumps(
                        {
                            "stream_type": "code_execution",
                            "chunk": {
                                "type": "error",
                                "content": f"Internal error processing execution output: {str(e)}",
                            },
                        }
                    )

        except Exception as stream_err:
            logging_utility.error(
                "Error during code_execution_client.stream_output: %s",
                str(stream_err),
                exc_info=True,
            )
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {
                        "type": "error",
                        "content": f"Failed to stream code execution: {str(stream_err)}",
                    },
                }
            )
            # Ensure flow continues to submit something if possible, or handle failure
            uploaded_files = []  # Reset uploaded files as execution failed

        # -------------------------------
        # Step 2: Construct signed URL list and markdown lines (Uses original uploaded_files)
        # -------------------------------
        logging_utility.info("Constructing URLs and markdown links...")
        markdown_lines = []
        url_list = []

        if uploaded_files:
            logging_utility.info(
                "Processing %d uploaded files for URLs/Markdown.", len(uploaded_files)
            )
            for (
                file_meta
            ) in uploaded_files:  # Use a different variable name like file_meta
                try:
                    file_id = file_meta.get("id")
                    filename = file_meta.get("filename")
                    presigned_url = file_meta.get(
                        "url"
                    )  # URL from _upload_generated_files

                    if not file_id or not filename:
                        logging_utility.warning(
                            "Skipping file metadata entry with missing id or filename: %s",
                            file_meta,
                        )
                        continue

                    # Determine the URL to use/display
                    display_url = None
                    if presigned_url:
                        # Check if it's the markdown format `[filename](<<url>>)`
                        if presigned_url.startswith("[") and presigned_url.endswith(
                            ")"
                        ):
                            match = re.search(r"\(\<\<(.*?)\>\>\)", presigned_url)
                            if match:
                                display_url = match.group(1)
                            else:
                                logging_utility.warning(
                                    "Could not extract URL from markdown-like string: %s",
                                    presigned_url,
                                )
                                # Fallback or handle error
                        else:
                            display_url = presigned_url  # Assume it's a direct URL

                    # Fallback if no presigned URL was successfully obtained or parsed
                    if not display_url:
                        # Construct a fallback download URL if your API supports it
                        # Adjust the host/path as needed
                        fallback_base = os.getenv(
                            "FILE_DOWNLOAD_BASE_URL", "http://localhost:9000"
                        )  # Example base URL
                        display_url = (
                            f"{fallback_base}/v1/files/download?file_id={file_id}"
                        )
                        logging_utility.info(
                            "Using fallback download URL for %s: %s",
                            filename,
                            display_url,
                        )

                    url_list.append(display_url)  # Add the URL for the assistant
                    markdown_lines.append(
                        f"[{filename}]({display_url})"
                    )  # Add markdown link for the user

                except Exception as e:
                    logging_utility.error(
                        "Error processing URL/Markdown for file %s: %s",
                        file_meta.get("id", "N/A"),
                        str(e),
                        exc_info=True,
                    )
                    # Add a placeholder if processing fails for a file
                    fn = file_meta.get("filename", "Unknown File")
                    markdown_lines.append(f"{fn}: Error generating link")

            # Content for the final user message (Step 4)
            final_content_for_assistant = "\n\n".join(
                markdown_lines
            )  # Use markdown links

        else:
            logging_utility.info(
                "No uploaded files found. Using code output buffer for content."
            )
            # Use the captured stdout/stderr if no files were generated
            final_content_for_assistant = "\n".join(hot_code_buffer).strip()
            # If buffer is empty, provide a default message
            if not final_content_for_assistant:
                final_content_for_assistant = (
                    "[Code executed successfully, but produced no output or files.]"
                )

        # -------------------------------
        # Step 3: Stream base64 previews for frontend rendering (Correct MIME Type Here)
        # -------------------------------
        if uploaded_files:
            logging_utility.info(
                "Streaming base64 previews for %d files...", len(uploaded_files)
            )
            # Assuming EntitiesInternalInterface provides file access
            # Ensure base URL is correctly configured
            entities_base_url = os.getenv(
                "ENTITIES_BASE_URL", "http://fastapi_cosmic_catalyst:9000"
            )

            for file_meta in uploaded_files:  # Use file_meta again
                file_id = file_meta.get("id")
                filename = file_meta.get("filename")

                if not file_id or not filename:
                    logging_utility.warning(
                        "Skipping base64 streaming for entry with missing id or filename: %s",
                        file_meta,
                    )
                    continue

                base64_str = None
                # <<< START MODIFICATION >>>
                # Dynamically determine MIME type based on filename *here*
                guessed_mime_type, _ = mimetypes.guess_type(filename)
                final_mime_type = (
                    guessed_mime_type
                    if guessed_mime_type
                    else "application/octet-stream"
                )
                logging_utility.info(
                    "Determined MIME type for '%s' (ID: %s) as: %s",
                    filename,
                    file_id,
                    final_mime_type,
                )
                # <<< END MODIFICATION >>>

                try:
                    # Fetch the base64 content using the file ID
                    base64_str = self.files.get_file_as_base64(file_id=file_id)
                    logging_utility.debug(
                        "Successfully fetched base64 for file %s (%s)",
                        filename,
                        file_id,
                    )

                except Exception as e:
                    logging_utility.error(
                        "Error fetching base64 for file %s (%s): %s",
                        filename,
                        file_id,
                        str(e),
                        exc_info=True,
                    )
                    # Send an error placeholder in the stream
                    base64_str = base64.b64encode(
                        f"Error retrieving content: {str(e)}".encode()
                    ).decode()  # Encode error message
                    final_mime_type = "text/plain"  # Set mime type to text for error

                # Yield the chunk with the corrected MIME type
                yield json.dumps(
                    {
                        "stream_type": "code_execution",
                        "chunk": {
                            "type": "code_interpreter_stream",
                            "content": {
                                "filename": filename,
                                "file_id": file_id,
                                "base64": base64_str,
                                "mime_type": final_mime_type,  # Use the dynamically determined type
                            },
                        },
                    }
                )
                logging_utility.info(
                    "Yielded base64 chunk for %s (%s) with MIME type %s",
                    filename,
                    file_id,
                    final_mime_type,
                )

        # -------------------------------
        # Step 4: Final frontend-visible chunk (Uses content generated in Step 2)
        # -------------------------------
        logging_utility.info("Yielding final content chunk for display.")
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {
                    "type": "content",
                    "content": final_content_for_assistant,  # Send the constructed markdown or buffer
                },
            }
        )

        # -------------------------------
        # Step 5: Log uploaded file contents for debug (Uses original uploaded_files)
        # -------------------------------
        # Note: 'uploaded_files' still contains the original mime_type from Step 1
        logging_utility.info(
            "Final uploaded_files metadata (original mime_type):\n%s",
            pprint.pformat(uploaded_files),
        )

        # -------------------------------
        # Step 6: Submit Tool Output (Uses url_list or final_content_for_assistant from Step 2)
        # -------------------------------
        try:
            # Choose content based on whether file URLs were generated
            content_to_submit = url_list if url_list else final_content_for_assistant
            submission_message = (
                CODE_ANALYSIS_TOOL_MESSAGE if url_list else final_content_for_assistant
            )  # Message for assistant context

            logging_utility.info(
                "Submitting tool output. Content type: %s",
                "URL List" if url_list else "Text Content",
            )
            # Ensure content_to_submit is not None (handle empty buffer case from Step 2)
            if content_to_submit is None:
                logging_utility.warning(
                    "Content to submit is None, submitting empty string."
                )
                content_to_submit = ""  # Avoid sending None

            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                # Decide precisely what the assistant needs: URLs or the text output?
                # If assistant only needs confirmation or URLs, use a standard message or url_list
                # If assistant needs the text output when no files, use final_content_for_assistant
                content=submission_message,  # Content for the assistant's context
                action=action,
                # Consider adding raw output if needed by submit_tool_output, e.g., tool_outputs=content_to_submit
            )
            logging_utility.info("Tool output submitted successfully.")

        except Exception as submit_err:
            # This is likely where the "Together SDK error: 422... 'input': None" occurred
            logging_utility.error(
                "Error submitting tool output: %s", str(submit_err), exc_info=True
            )
            # Optionally yield another error to the frontend if submission fails critically
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {
                        "type": "error",
                        "content": f"Failed to submit results: {str(submit_err)}",
                    },
                }
            )

    def handle_shell_action(self, thread_id, run_id, assistant_id, arguments_dict):
        import json

        from entities_api.platform_tools.computer.shell_command_interface import (
            run_shell_commands,
        )

        # Create an action for the computer command execution
        action = self.action_service.create_action(
            tool_name="computer", run_id=run_id, function_args=arguments_dict
        )

        # Extract commands from the arguments dictionary
        commands = arguments_dict.get("commands", [])
        bash_buffer = []

        accumulated_content = ""

        # Stream the execution output and accumulate chunks
        for chunk in run_shell_commands(commands, thread_id=thread_id):
            try:

                accumulated_content += chunk

                yield chunk  # Preserve streaming for real-time output

            except json.JSONDecodeError:
                # Handle invalid JSON chunks
                error_message = "Error: Invalid JSON chunk received from computer command execution."
                self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=error_message,
                    action=action,
                )
                raise RuntimeError(error_message)

        # Check if bash_buffer is empty (no output was generated)
        if not accumulated_content:
            error_message = "Error: No computer output was generated. The command may have failed or produced no output."
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=error_message,
                action=action,
            )
            raise RuntimeError(error_message)

        # Submit the final output after execution completes
        self.submit_tool_output(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=accumulated_content,
            action=action,
        )

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
    def stream_response(
        self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=False
    ):
        """
        Streams tool responses in real time using the TogetherAI SDK.
        - Yields each token chunk immediately, split by reasoning tags.
        - Accumulates the full response for final validation.
        - Supports mid-stream cancellation.
        - Strips markdown triple backticks from the final accumulated content.
        - Excludes all characters prior to (and including) the partial code-interpreter match.
        """
        pass

    def stream_function_call_output(
        self, thread_id, run_id, assistant_id, model, name=None, stream_reasoning=False
    ):
        """
        Streaming handler for tool-based assistant responses, including reasoning and content.

        Injects protocol reminders, initiates assistant conversation, and yields output chunks.
        Handles reasoning content (`<think>...</think>`) alongside normal responses.

        Args:
            thread_id (str): UUID of conversation.
            run_id (str): Execution context.
            assistant_id (str): Assistant identity.
            model (str): Model to use.
            name (str): Name of the invoked tool.
            stream_reasoning (bool): Whether to include reasoning output.

        Yields:
            JSON stringified chunks.
        """
        logging_utility.info(
            "Processing conversation for thread_id: %s, run_id: %s, assistant_id: %s",
            thread_id,
            run_id,
            assistant_id,
        )

        # Choose reminder message based on tool
        reminder = (
            CODE_INTERPRETER_MESSAGE
            if name == "code_interpreter"
            else DEFAULT_REMINDER_MESSAGE
        )

        # Inject system reminder into context

        self.message_service.create_message(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=reminder,
            role="user",
        )
        logging_utility.info("Sent reminder message to assistant: %s", reminder)

        # Begin streaming via hyperbolic backend
        try:
            stream_generator = self.stream_response_hyperbolic(
                thread_id=thread_id,
                message_id=None,  # Optional: extend interface to capture user msg ID if needed
                run_id=run_id,
                assistant_id=assistant_id,
                model=model,
                stream_reasoning=True,
            )

            assistant_reply = ""
            reasoning_content = ""

            for chunk in stream_generator:
                parsed = json.loads(chunk) if isinstance(chunk, str) else chunk

                chunk_type = parsed.get("type")
                content = parsed.get("content", "")

                if chunk_type == "reasoning":
                    reasoning_content += content
                    yield json.dumps({"type": "reasoning", "content": content})

                elif chunk_type == "content":
                    assistant_reply += content
                    yield json.dumps({"type": "content", "content": content}) + "\n"

                elif chunk_type == "error":
                    logging_utility.error("Error in assistant stream: %s", content)
                    yield json.dumps({"type": "error", "content": content})
                    return

                else:
                    # Default fallback for other chunk types (optional: forward raw)
                    yield json.dumps(parsed)

                time.sleep(0.01)

        except Exception as e:
            error_msg = f"[ERROR] Hyperbolic stream failed: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            yield json.dumps({"type": "error", "content": error_msg})
            return

        # Finalize only if content was generated
        if assistant_reply:
            full_output = reasoning_content + assistant_reply
            self.finalize_conversation(
                assistant_reply=full_output,
                thread_id=thread_id,
                assistant_id=assistant_id,
                run_id=run_id,
            )
            logging_utility.info("Assistant response finalized and stored.")

        self.run_service.update_run_status(run_id, validator.StatusEnum.completed)
        if reasoning_content:
            logging_utility.info("Final reasoning content: %s", reasoning_content)

    def _process_code_interpreter_chunks(self, content_chunk, code_buffer):
        """
        Process code chunks while in code mode.

        Appends the incoming content_chunk to code_buffer,
        then extracts a single line (if a newline exists) and handles buffer overflow.

        Returns:
            tuple: (results, updated code_buffer)
                - results: list of JSON strings representing code chunks.
                - updated code_buffer: the remaining buffer content.
        """

        self.code_mode = True

        results = []
        code_buffer += content_chunk

        # Process one line at a time if a newline is present.
        if "\n" in code_buffer:
            newline_pos = code_buffer.find("\n") + 1
            line_chunk = code_buffer[:newline_pos]
            code_buffer = code_buffer[newline_pos:]
            # Optionally, you can add security checks here for forbidden patterns.
            results.append(json.dumps({"type": "hot_code", "content": line_chunk}))

        # Buffer overflow protection: if the code_buffer grows too large,
        # yield its content as a chunk and reset it.
        if len(code_buffer) > 100:
            results.append(json.dumps({"type": "hot_code", "content": code_buffer}))
            code_buffer = ""

        return results, code_buffer

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

        # interface = self.internal_sdk_interface()

        assistant = self.assistant_service.retrieve_assistant(assistant_id=assistant_id)

        associated_tools = self.tool_service.list_tools(assistant_id=assistant_id)

        tools = self.tool_service.list_tools(
            assistant_id=assistant_id, restructure=True
        )

        # Get the current date and time
        today = datetime.now()

        # Format the date and time as a string
        formatted_datetime = today.strftime("%Y-%m-%d %H:%M:%S")

        # Include the formatted date and time in the system message
        conversation_history = self.message_service.get_formatted_messages(
            thread_id,
            system_message="tools:"
            + str(tools)
            + "\n"
            + assistant.instructions
            + "\n"
            + f"Today's date and time:, {formatted_datetime}",
        )

        messages = self.normalize_roles(conversation_history)

        # Sliding Windows Truncation
        truncated_message = self.conversation_truncator.truncate(messages)

        if trunk:
            return truncated_message
        else:
            return messages

    def parse_and_set_function_calls(
        self, accumulated_content: str, assistant_reply: str
    ) -> None:
        """
        Parses the accumulated content for function calls.

        This method performs the following:
          - Logs the raw accumulated content.
          - Normalizes the JSON output using `ensure_valid_json`. It expects the entire input to be JSON;
            otherwise, it returns False.
          - Validates the function call structure via `is_valid_function_call_response`.
          - Handles complex vector search calls using `is_complex_vector_search`.
          - Sets the tool response and function call state accordingly.
          - If tool invocations are detected in multi-line text and no prior valid state exists, it updates
            the state with the first invocation.

        Parameters:
            accumulated_content (str): The raw content accumulated from streaming responses.
            assistant_reply (str): The final form of the assistants reply.
        """

        if accumulated_content:
            logging_utility.debug("Raw accumulated content: %s", accumulated_content)

            # Normalize JSON output from the accumulated content.
            json_accumulated_content = self.ensure_valid_json(text=accumulated_content)

            if json_accumulated_content:
                # Validate function call structure.
                function_call = self.is_valid_function_call_response(
                    json_data=json_accumulated_content
                )
                logging_utility.debug("Valid Function call: %s", function_call)

                # Check for complex vector search requirements.
                complex_vector_search = self.is_complex_vector_search(
                    data=json_accumulated_content
                )

                # If either valid function call or complex vector search is detected, update the state.
                if function_call or complex_vector_search:
                    self.set_tool_response_state(True)
                    logging_utility.debug(
                        "Response State: %s", self.get_tool_response_state()
                    )
                    self.set_function_call_state(json_accumulated_content)
                    logging_utility.debug(
                        "Function call State: %s", self.get_function_call_state()
                    )

        # Check for tool invocations embedded in multi-line text.
        tool_invocation_in_multi_line_text = (
            self.extract_function_calls_within_body_of_text(text=assistant_reply)
        )
        # --------------------------------------------------
        #  The assistant may wrap a function call in
        #  response text. This block  will catch that
        # --------------------------------------------------
        if tool_invocation_in_multi_line_text and not self.get_tool_response_state():

            logging_utility.debug(
                "Embedded Function Call detected : %s",
                tool_invocation_in_multi_line_text,
            )

            self.set_tool_response_state(True)
            self.set_function_call_state(tool_invocation_in_multi_line_text)

            self.set_function_call_state(tool_invocation_in_multi_line_text[0])

    def stream_response_hyperbolic_llama3(
        self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=True
    ):
        """
        Llama 3 (Hyperbolic) streaming with content, code, and function call handling.
        Mirrors stream_response_hyperbolic structure, excluding reasoning logic.
        """
        self.start_cancellation_listener(run_id)

        model = "meta-llama/Llama-3.3-70B-Instruct"
        request_payload = {
            "model": model,
            "messages": self._set_up_context_window(
                assistant_id, thread_id, trunk=True
            ),
            "max_tokens": None,
            "temperature": 0.6,
            "stream": True,
        }

        assistant_reply = ""
        accumulated_content = ""
        code_mode = False
        code_buffer = ""

        try:
            response = self.hyperbolic_client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    yield json.dumps({"type": "error", "content": "Run cancelled"})
                    break

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta
                delta_content = getattr(delta, "content", "")
                if not delta_content:
                    continue

                sys.stdout.write(delta_content)
                sys.stdout.flush()

                segments = [delta_content]

                for seg in segments:
                    if not seg:
                        continue

                    assistant_reply += seg
                    accumulated_content += seg

                    # --- Code Interpreter Trigger Check ---
                    partial_match = self.parse_code_interpreter_partial(
                        accumulated_content
                    )

                    if not code_mode and partial_match:
                        full_match = partial_match.get("full_match")
                        if full_match:
                            match_index = accumulated_content.find(full_match)
                            if match_index != -1:
                                accumulated_content = accumulated_content[
                                    match_index + len(full_match) :
                                ]
                        code_mode = True
                        code_buffer = partial_match.get("code", "")
                        self.code_mode = True
                        yield json.dumps({"type": "hot_code", "content": "```python\n"})
                        continue

                    if code_mode:
                        results, code_buffer = self._process_code_interpreter_chunks(
                            seg, code_buffer
                        )
                        for r in results:
                            yield r
                            assistant_reply += r
                        continue

                    if not code_buffer:
                        yield json.dumps({"type": "content", "content": seg}) + "\n"

                time.sleep(0.05)

        except Exception as e:
            error_msg = f"Llama 3 / Hyperbolic SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            self.handle_error(assistant_reply, thread_id, assistant_id, run_id)
            yield json.dumps({"type": "error", "content": error_msg})
            return

        # Finalize assistant message and parse function calls
        if assistant_reply:
            self.finalize_conversation(assistant_reply, thread_id, assistant_id, run_id)

        if accumulated_content:
            self.parse_and_set_function_calls(accumulated_content, assistant_reply)
            logging_utility.info(f"Function call parsing completed for run {run_id}")

        self.run_service.update_run_status(run_id, validator.StatusEnum.completed)

    def stream_response_hyperbolic(
        self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=True
    ):
        """
        Process conversation with dual streaming of content and reasoning.
        If a tool call trigger is detected, update run status to 'action_required',
        then wait for the status change and reprocess the original prompt.

        This function splits incoming tokens into reasoning and content segments
        (using <think> tags) while also handling a code mode. When a partial
        code-interpreter match is found, it enters code mode, processes and streams
        raw code via the _process_code_interpreter_chunks helper, and emits a start-of-code marker.

        Accumulated content is later used to finalize the conversation and validate
        tool responses.
        """
        # Start cancellation listener
        self.start_cancellation_listener(run_id)

        # Force correct model value via mapping (defaulting if not mapped)
        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)
        else:
            model = "deepseek-ai/DeepSeek-V3"

        request_payload = {
            "model": model,
            "messages": self._set_up_context_window(
                assistant_id, thread_id, trunk=True
            ),
            "max_tokens": None,
            "temperature": 0.6,
            "stream": True,
        }

        assistant_reply = ""
        accumulated_content = ""
        reasoning_content = ""
        in_reasoning = False
        code_mode = False
        code_buffer = ""
        matched = False

        try:
            # Using self.client for streaming responses; adjust if deepseek_client is required.
            response = self.hyperbolic_client.chat.completions.create(**request_payload)

            for token in response:
                if self.check_cancellation_flag():
                    logging_utility.warning(f"Run {run_id} cancelled mid-stream")
                    yield json.dumps({"type": "error", "content": "Run cancelled"})
                    break

                if not hasattr(token, "choices") or not token.choices:
                    continue

                delta = token.choices[0].delta

                # Process any explicit reasoning content from delta.
                delta_reasoning = getattr(delta, "reasoning_content", "")
                if delta_reasoning:
                    reasoning_content += delta_reasoning
                    yield json.dumps({"type": "reasoning", "content": delta_reasoning})

                # Process content from delta.
                delta_content = getattr(delta, "content", "")
                if not delta_content:
                    continue

                # Optionally output raw content for debugging.
                sys.stdout.write(delta_content)
                sys.stdout.flush()

                # Split the content based on reasoning tags (<think> and </think>)
                segments = (
                    self.REASONING_PATTERN.split(delta_content)
                    if hasattr(self, "REASONING_PATTERN")
                    else [delta_content]
                )
                for seg in segments:
                    if not seg:
                        continue

                    # Check for reasoning start/end tags.
                    if seg == "<think>":
                        in_reasoning = True
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                        continue
                    elif seg == "</think>":
                        in_reasoning = False
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning tag: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                        continue

                    if in_reasoning:
                        # If within reasoning, yield as reasoning content.
                        reasoning_content += seg
                        logging_utility.debug("Yielding reasoning segment: %s", seg)
                        yield json.dumps({"type": "reasoning", "content": seg})
                    else:
                        # Outside reasoning: process as normal content.
                        assistant_reply += seg
                        accumulated_content += seg
                        logging_utility.debug("Processing content segment: %s", seg)

                        # Check if a code-interpreter trigger is found (and not already in code mode).
                        partial_match = self.parse_code_interpreter_partial(
                            accumulated_content
                        )

                        if not code_mode:

                            if partial_match:
                                full_match = partial_match.get("full_match")
                                if full_match:
                                    match_index = accumulated_content.find(full_match)
                                    if match_index != -1:
                                        # Remove all content up to and including the trigger.
                                        accumulated_content = accumulated_content[
                                            match_index + len(full_match) :
                                        ]
                                code_mode = True
                                code_buffer = partial_match.get("code", "")

                                # Emit start-of-code block marker.
                                self.code_mode = True
                                yield json.dumps(
                                    {"type": "hot_code", "content": "```python\n"}
                                )
                                continue  # Skip further processing of this segment.

                        # If already in code mode, delegate to code-chunk processing.
                        if code_mode:

                            results, code_buffer = (
                                self._process_code_interpreter_chunks(seg, code_buffer)
                            )
                            for r in results:
                                yield r  # Yield raw code line(s).
                                assistant_reply += r  # Optionally accumulate the code.

                            continue

                        # Yield non-code content as normal.
                        if not code_buffer:
                            yield json.dumps({"type": "content", "content": seg}) + "\n"
                        else:
                            continue

                # Slight pause to allow incremental delivery.
                time.sleep(0.05)

        except Exception as e:
            error_msg = f"Hyperbolic SDK error: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            combined = reasoning_content + assistant_reply
            self.handle_error(combined, thread_id, assistant_id, run_id)
            yield json.dumps({"type": "error", "content": error_msg})
            return

        # Finalize conversation if there's any assistant reply content.
        if assistant_reply:
            combined = reasoning_content + assistant_reply
            self.finalize_conversation(combined, thread_id, assistant_id, run_id)

        # -----------------------------------------
        #  Parsing the complete accumulated content
        #  for function calls.
        # -----------------------------------------
        if accumulated_content:
            self.parse_and_set_function_calls(accumulated_content, assistant_reply)

        self.run_service.update_run_status(run_id, validator.StatusEnum.completed)
        if reasoning_content:
            logging_utility.info("Final reasoning content: %s", reasoning_content)

    def process_function_calls(self, thread_id, run_id, assistant_id, model=None):
        """
        Process the pending function call state and yield output chunks accordingly.

        This method checks the current function call state using self.get_function_call_state().
        If a function call exists, it determines whether it belongs to PLATFORM_TOOLS or is a user-side call.

        For function calls in PLATFORM_TOOLS:
          - If the call is for "code_interpreter", it delegates to handle_code_interpreter_action and yields its output.
          - Otherwise, it processes the call using _process_platform_tool_calls.
          In both cases, the output is streamed via stream_function_call_output and yielded.

        For user-side function calls (i.e., those not in PLATFORM_TOOLS):
          - It processes the call using _process_tool_calls.
          - Then, it streams and yields the output via stream_function_call_output.

        Parameters:
          thread_id : Any
              Identifier for the current conversation thread.
          run_id : Any
              Unique identifier for the current execution or run.
          assistant_id : Any
              Identifier for the assistant handling the conversation.
          model : Optional[Any]
              The model used during processing; can be utilized for context in tool call outputs.

        Yields:
          chunk : Any
              Chunks of output generated by the processing of function calls.
        """
        fc_state = self.get_function_call_state()

        if not fc_state:
            return

        if fc_state.get("name") in PLATFORM_TOOLS:
            if fc_state.get("name") == "code_interpreter":
                for chunk in self.handle_code_interpreter_action(
                    thread_id=thread_id,
                    run_id=run_id,
                    assistant_id=assistant_id,
                    arguments_dict=fc_state.get("arguments"),
                ):
                    yield chunk

                for chunk in self.stream_function_call_output(
                    thread_id=thread_id,
                    run_id=run_id,
                    model=model,
                    assistant_id=assistant_id,
                    # name='code_interpreter'
                ):
                    yield chunk

            if fc_state.get("name") == "computer":
                for chunk in self.handle_shell_action(
                    thread_id=thread_id,
                    run_id=run_id,
                    assistant_id=assistant_id,
                    arguments_dict=fc_state.get("arguments"),
                ):
                    yield chunk

                for chunk in self.stream_function_call_output(
                    thread_id=thread_id,
                    run_id=run_id,
                    model=model,
                    assistant_id=assistant_id,
                ):
                    yield chunk

            else:

                # --------------------------------------
                # Exclude special case tools from further
                # Handling here.
                # ---------------------------------------
                if not fc_state.get("name") in SPECIAL_CASE_TOOL_HANDLING:

                    self._process_platform_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=fc_state,
                        run_id=run_id,
                    )
                    # -----------------------------
                    # Remind the assistant to synthesise
                    # a contextual response on tool submission
                    # -----------------------------
                    for chunk in self.stream_function_call_output(
                        thread_id=thread_id,
                        run_id=run_id,
                        model=model,
                        assistant_id=assistant_id,
                    ):
                        yield chunk

                else:
                    # -----------------------
                    # Handles consumer side tool calls.
                    # ------------------------
                    self._process_tool_calls(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        content=fc_state,
                        run_id=run_id,
                    )
                    for chunk in self.stream_function_call_output(
                        thread_id=thread_id, run_id=run_id, assistant_id=assistant_id
                    ):
                        yield chunk

    @abstractmethod
    def process_conversation(
        self, thread_id, message_id, run_id, assistant_id, model, stream_reasoning=False
    ):
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
