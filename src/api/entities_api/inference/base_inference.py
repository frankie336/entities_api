import abc
import base64
import inspect
import json
import mimetypes
import os
import pprint
import re
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable, Dict, Generator, Optional

import httpx
from openai import OpenAI
from projectdavid import Entity
from projectdavid.clients.actions_client import ActionsClient
from projectdavid.clients.assistants_client import AssistantsClient
from projectdavid.clients.files_client import FileClient
from projectdavid.clients.messages_client import MessagesClient
from projectdavid.clients.runs import RunsClient
from projectdavid.clients.threads_client import ThreadsClient
from projectdavid.clients.tools_client import ToolsClient
from projectdavid.clients.users_client import UsersClient
from projectdavid.clients.vectors import VectorStoreClient
from projectdavid_common import ValidationInterface
from projectdavid_common.constants.ai_model_map import MODEL_MAP
from together import Together

from entities_api.constants.assistant import (
    CODE_ANALYSIS_TOOL_MESSAGE, CODE_INTERPRETER_MESSAGE,
    DEFAULT_REMINDER_MESSAGE, PLATFORM_TOOLS,
    WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS)
from entities_api.constants.platform import (ERROR_NO_CONTENT,
                                             SPECIAL_CASE_TOOL_HANDLING)
from entities_api.platform_tools.code_interpreter.code_execution_client import \
    StreamOutput
from entities_api.platform_tools.platform_tool_service import \
    PlatformToolService
from entities_api.services.conversation_truncator import ConversationTruncator
from entities_api.services.logging_service import LoggingUtility

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
        base_url=os.getenv("BASE_URL"),
        api_key=None,
        assistant_id=None,
        thread_id=None,
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

        # Instantiate the default OpenAI client
        try:
            self.openai_client = OpenAI(
                api_key=os.getenv("TOGETHER_API_KEY"),
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0, read=30.0),
            )
        except Exception as e:
            logging_utility.error(
                "Failed to initialize default OpenAI client: %s", e, exc_info=True
            )
            self.openai_client = None

        # Instantiate the default Together client
        try:
            self.together_client = Together(
                api_key=os.getenv("TOGETHER_API_KEY"),
            )

        except Exception as e:
            logging_utility.error(
                "Failed to initialize default OpenAI client: %s", e, exc_info=True
            )
            self.openai_client = None

        # 2. Initialize the default project_david client
        project_david_api_key = os.getenv("ADMIN_API_KEY")

        project_david_base_url = self.base_url

        try:
            if not project_david_api_key:
                raise ConfigurationError("ADMIN_API_KEY is not set.")
            if not project_david_base_url:
                raise ConfigurationError(
                    "Base URL for Project David client is not set."
                )

            self.project_david_client = Entity(
                api_key=project_david_api_key,
                base_url=project_david_base_url,
                # time out handled internally
            )
            logging_utility.debug(
                "Default project_david client initialized successfully."
            )
        except Exception as e:
            logging_utility.error(
                "Failed to initialize default project_david client: %s",
                e,
                exc_info=True,
            )
            self.project_david_client = None  # Ensure it's None on failure

        self.truncator_params = {
            "model_name": model_name,
            "max_context_window": max_context_window,
            "threshold_percentage": threshold_percentage,
        }

        logging_utility.info("BaseInference initialized with lazy service loading.")
        self.setup_services()

    def setup_services(self):
        """Initialize all lazy-loadable service classes"""
        pass

    def _get_service(self, service_class, custom_params=None):
        """Intelligent service initializer with parametric awareness"""
        if service_class not in self._services:
            try:
                if service_class == PlatformToolService:
                    self._services[service_class] = self._init_platform_tool_service()
                elif service_class == ConversationTruncator:
                    self._services[service_class] = self._init_conversation_truncator()
                elif service_class == StreamOutput:
                    self._services[service_class] = self._init_stream_output()
                else:
                    self._services[service_class] = self._init_general_service(
                        service_class, custom_params
                    )
                logging_utility.debug(f"Initialized {service_class.__name__}")
            except Exception as e:
                logging_utility.error(
                    f"Service init failed for {service_class.__name__}: {str(e)}",
                    exc_info=True,
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

    def _init_conversation_truncator(self):
        return ConversationTruncator(**self.truncator_params)

    def _init_stream_output(self):
        return StreamOutput()

    def _init_general_service(self, service_class, custom_params):
        if custom_params is not None:
            return service_class(*custom_params)
        signature = inspect.signature(service_class.__init__)
        params = self._resolve_init_parameters(signature)
        return service_class(*params)

    @lru_cache(maxsize=32)
    def _resolve_init_parameters(self, signature):
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
        if not self.get_assistant_id():
            raise ConfigurationError("Platform services require assistant_id")
        if not hasattr(self, "_platform_credentials_verified"):
            try:
                self._platform_credentials_verified = True
            except Exception as e:
                raise AuthenticationError(f"Credential validation failed: {str(e)}")

    @lru_cache(maxsize=32)
    def _get_together_client(
        self, api_key: Optional[str], base_url: Optional[str] = None
    ) -> Together:
        """
        Retrieves or creates a Project David client for the given API key.
        Uses an LRU cache for reuse. If api_key is None, returns the default client.
        """
        if api_key:
            logging_utility.debug("Creating client for specific key (not cached).")
            try:
                return Together(
                    api_key=api_key,
                    # base_url=base_url,
                )
            except Exception as e:
                logging_utility.error(
                    "Failed to create specific TogetherAI client: %s",
                    e,
                    exc_info=True,
                )
                if self.together_client:
                    logging_utility.warning(
                        "Falling back to default client due to error."
                    )
                    return self.together_client
                else:
                    raise RuntimeError(
                        "Default TogetherAI client is not initialized, and specific client creation failed."
                    )
        else:
            if self.together_client:
                logging_utility.debug(
                    "Using default project_david client (no specific key provided)."
                )
                return self.together_client
            else:
                raise RuntimeError("Default TogetherAI client is not initialized.")

    @lru_cache(maxsize=32)
    def _get_project_david_client(
        self, api_key: Optional[str], base_url: Optional[str] = None
    ) -> Entity:
        """
        Retrieves or creates a Project David client for the given API key.
        Uses an LRU cache for reuse. If api_key is None, returns the default client.
        """
        if api_key:
            logging_utility.debug("Creating client for specific key (not cached).")
            try:
                return Entity(
                    api_key=api_key,
                    base_url=base_url,
                )
            except Exception as e:
                logging_utility.error(
                    "Failed to create specific project_david client: %s",
                    e,
                    exc_info=True,
                )
                if self.project_david_client:
                    logging_utility.warning(
                        "Falling back to default client due to error."
                    )
                    return self.project_david_client
                else:
                    raise RuntimeError(
                        "Default project_david client is not initialized, and specific client creation failed."
                    )
        else:
            if self.project_david_client:
                logging_utility.debug(
                    "Using default project_david client (no specific key provided)."
                )
                return self.project_david_client
            else:
                raise RuntimeError("Default project_david client is not initialized.")

    @lru_cache(maxsize=32)
    def _get_openai_client(
        self, api_key: Optional[str], base_url: Optional[str] = None
    ) -> OpenAI:
        """
        Retrieves or creates an OpenAI client for the given API key.
        Uses an LRU cache for reuse. If api_key is None, returns the default client.
        """
        if api_key:
            logging_utility.debug("Creating client for specific key (not cached).")
            try:
                return OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=httpx.Timeout(30.0, read=30.0),
                )
            except Exception as e:
                logging_utility.error(
                    "Failed to create specific OpenAI client: %s", e, exc_info=True
                )
                if self.openai_client:
                    logging_utility.warning(
                        "Falling back to default client due to error."
                    )
                    return self.openai_client
                else:
                    raise RuntimeError(
                        "Default OpenAI client is not initialized, and specific client creation failed."
                    )
        else:
            if self.openai_client:
                logging_utility.debug(
                    "Using default OpenAI client (no specific key provided)."
                )
                return self.openai_client
            else:
                raise RuntimeError("Default OpenAI client is not initialized.")

    def get_assistant_id(self):
        return self.assistant_id

    @property
    def user_client(self):
        return self._get_service(
            UsersClient,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    @property
    def assistant_service(self):
        return self._get_service(
            AssistantsClient,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    # ----------------------
    # A tread is never created
    # by processing logic
    # -------------------------
    @property
    def thread_service(self):
        return self._get_service(
            ThreadsClient,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    @property
    def message_service(self):
        return self._get_service(
            MessagesClient,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    @property
    def run_service(self):
        return self._get_service(
            RunsClient,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    @property
    def tool_service(self):
        return self._get_service(
            ToolsClient,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    @property
    def platform_tool_service(self):
        return self._get_service(
            PlatformToolService,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    @property
    def action_client(self):
        return self._get_service(
            ActionsClient,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    @property
    def vector_store_service(self):
        return self._get_service(
            VectorStoreClient,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    @property
    def files(self):
        return self._get_service(
            FileClient,
            custom_params=[os.getenv("BASE_URL"), os.getenv("ADMIN_API_KEY")],
        )

    @property
    def code_execution_client(self):
        return self._get_service(StreamOutput)

    @property
    def conversation_truncator(self):
        return self._get_service(ConversationTruncator)

    # -------------------------------------------------
    # -ENTITIES STATE INFORMATION-
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

    @abc.abstractmethod
    def stream(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Begin a structured streaming session from the assistant model.

        Args:
            thread_id (str): The thread ID associated with the message.
            message_id (str): The specific message ID being streamed.
            run_id (str): The ID of the current assistant run.
            assistant_id (str): The ID of the assistant handling the conversation.
            model (Any): Model identifier or object to be mapped and resolved.
            stream_reasoning (bool): Whether to emit reasoning deltas (`<think>` segments).
            api_key (Optional[str]): Optional API key to override default config.

        Yields:
            str: JSON string-encoded response chunks (type: "content", "reasoning", "hot_code", "error")
        """
        pass

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

            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )

            client.messages.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply,
                role="assistant",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True,
            )
            logging_utility.info("Partial assistant response stored successfully.")

            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )

            client.runs.update_run_status(run_id, validator.StatusEnum.failed)

    def finalize_conversation(self, assistant_reply, thread_id, assistant_id, run_id):
        """Finalize the conversation by storing the assistant's reply."""

        if assistant_reply:

            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )

            message = client.messages.save_assistant_message_chunk(
                thread_id=thread_id,
                content=assistant_reply,
                role="assistant",
                assistant_id=assistant_id,
                sender_id=assistant_id,
                is_last_chunk=True,
            )

            logging_utility.info("Assistant response stored successfully.")

            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )

            client.runs.update_run_status(run_id, validator.StatusEnum.completed)

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

        client = self._get_project_david_client(
            api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
        )

        def listen_for_cancellation():
            event_handler = EntitiesEventHandler(
                run_service=client.runs,
                action_service=client.actions,
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

    def _process_tool_calls(self, thread_id, assistant_id, content, run_id, api_key):

        # Save the tool invocation for state management.
        action = self.action_client.create_action(
            tool_name=content["name"], run_id=run_id, function_args=content["arguments"]
        )

        logging_utility.debug(
            "Created action %s for tool %s", action.id, content["name"]
        )

        # Update run status to 'action_required'
        client = self._get_project_david_client(
            api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
        )

        client.runs.update_run_status(
            run_id=run_id, new_status=validator.StatusEnum.pending_action
        )
        logging_utility.info(f"Run {run_id} status updated to action_required")

        # Now wait for the run's status to change from 'action_required'.
        while True:

            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )

            run = client.runs.retrieve_run(run_id)
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

            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )

            client.messages.submit_tool_output(
                thread_id=thread_id,
                content=content,
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy",
            )
            self.action_client.update_action(action_id=action.id, status="completed")
            logging_utility.debug(
                "Tool output submitted successfully for action %s", action.id
            )

        except Exception as e:
            logging_utility.error(
                "Failed to submit tool output for action %s: %s", action.id, str(e)
            )
            self.action_client.update_action(action_id=action.id, status="failed")
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
            action = self.action_client.create_action(
                tool_name=content["name"],
                run_id=run_id,
                function_args=content["arguments"],
            )

            logging_utility.debug(
                "Created action %s for tool %s", action.id, content["name"]
            )

            # Update run status
            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )

            client.runs.update_run_status(
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
            self.action_client.update_action(action_id=action.id, status="failed")
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

            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )

            client.messages.submit_tool_output(
                thread_id=thread_id,
                content=content,
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy",  # Replace with actual tool_id if available
            )

            # Update action status
            self.action_client.update_action(action_id=action.id, status="completed")
            logging_utility.debug(
                "Tool output submitted successfully for action %s", action.id
            )
        except Exception as e:
            # Log the error
            logging_utility.error(
                "Failed to submit tool output for action %s: %s", action.id, str(e)
            )

            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )

            # Send the error message to the user
            client.messages.submit_tool_output(
                thread_id=thread_id,
                content=f"ERROR: {str(e)}",
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy",  # Replace with actual tool_id if available
            )

            # Update action status to 'failed'
            self.action_client.update_action(action_id=action.id, status="failed")

            # Re-raise the exception for further handling
            raise

    def handle_code_interpreter_action(
        self, thread_id, run_id, assistant_id, arguments_dict
    ):

        action = self.action_client.create_action(
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

        from entities_api.platform_tools.computer.shell_command_interface import \
            run_shell_commands

        # Create an action for the computer command execution
        action = self.action_client.create_action(
            tool_name="computer", run_id=run_id, function_args=arguments_dict
        )

        # Extract commands from the arguments dictionary
        commands = arguments_dict.get("commands", [])

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

    def stream_function_call_output(
        self,
        thread_id,
        run_id,
        assistant_id,
        model,
        stream: Callable[..., Generator[str, None, None]],
        name=None,
        stream_reasoning=False,
        api_key: Optional[str] = None,
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
            api_key: Optional[str]: provider api key
            stream (str): Stream to use.

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

        client = self._get_project_david_client(
            api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
        )

        client.messages.create_message(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=reminder,
            role="user",
        )
        logging_utility.info("Sent reminder message to assistant: %s", reminder)

        try:
            stream_generator = stream(
                thread_id=thread_id,
                message_id=None,
                run_id=run_id,
                assistant_id=assistant_id,
                model=model,
                stream_reasoning=True,
                api_key=api_key,
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

        client = self._get_project_david_client(
            api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
        )

        assistant = client.assistants.retrieve_assistant(assistant_id=assistant_id)

        tools = self.tool_service.list_tools(
            assistant_id=assistant_id, restructure=True
        )

        # Get the current date and time
        today = datetime.now()

        # Format the date and time as a string
        formatted_datetime = today.strftime("%Y-%m-%d %H:%M:%S")
        # Include the formatted date and time in the system message
        conversation_history = client.messages.get_formatted_messages(
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
    ) -> Optional[Dict[str, Any]]:
        """
        Parses the accumulated content for function calls.

        Returns:
            dict | None: The parsed function call payload if detected, else None.
        """
        parsed_function_call = None

        if accumulated_content:
            logging_utility.debug("Raw accumulated content: %s", accumulated_content)

            json_accumulated_content = self.ensure_valid_json(text=accumulated_content)

            if json_accumulated_content:
                function_call = self.is_valid_function_call_response(
                    json_data=json_accumulated_content
                )
                logging_utility.debug("Valid Function call: %s", function_call)

                complex_vector_search = self.is_complex_vector_search(
                    data=json_accumulated_content
                )

                if function_call or complex_vector_search:
                    self.set_tool_response_state(True)
                    self.set_function_call_state(json_accumulated_content)
                    parsed_function_call = json_accumulated_content
                    logging_utility.debug(
                        "Function call State set with payload: %s", parsed_function_call
                    )

        if not parsed_function_call:
            tool_invocation_in_multi_line_text = (
                self.extract_function_calls_within_body_of_text(text=assistant_reply)
            )
            if (
                tool_invocation_in_multi_line_text
                and not self.get_tool_response_state()
            ):
                logging_utility.debug(
                    "Embedded Function Call detected: %s",
                    tool_invocation_in_multi_line_text,
                )
                self.set_tool_response_state(True)
                embedded_call = tool_invocation_in_multi_line_text[0]
                self.set_function_call_state(embedded_call)
                parsed_function_call = embedded_call

        return parsed_function_call

    def process_function_calls(
        self, thread_id, run_id, assistant_id, model=None, api_key=None
    ):
        """
        Process pending function calls, route to handlers, and stream output.
        """
        fc_state = self.get_function_call_state()
        if not fc_state:
            return

        tool_name = fc_state.get("name")
        arguments_dict = fc_state.get("arguments")

        # --- Specific Platform Tool Handling ---
        if tool_name == "code_interpreter":

            yield from self.handle_code_interpreter_action(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=arguments_dict,
            )

        elif tool_name == "computer":
            yield from self.handle_shell_action(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=arguments_dict,
            )

        # --- General Platform Tool Handling ---
        elif tool_name in PLATFORM_TOOLS:  # Assumes PLATFORM_TOOLS is defined

            # Assumes SPECIAL_CASE_TOOL_HANDLING is defined
            if tool_name not in SPECIAL_CASE_TOOL_HANDLING:
                # Standard platform tools
                self._process_platform_tool_calls(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=fc_state,
                    run_id=run_id,
                )
            else:
                # Special-case platform tools (using consumer tool processing)
                self._process_tool_calls(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=fc_state,
                    run_id=run_id,
                )

        # --- Consumer Tool Handling ---
        else:
            # Non-platform (consumer) tools

            self._process_tool_calls(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=fc_state,
                run_id=run_id,
                api_key=api_key,
            )

        # --- Stream Output ---
        # if processed:
        # yield from self.stream_function_call_output(
        # thread_id=thread_id,
        # run_id=run_id,
        # model=model,
        # stream=self.stream,
        # assistant_id=assistant_id,
        # api_key=api_key,
        # )

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
        return self.user_client.get_user(user_id)
