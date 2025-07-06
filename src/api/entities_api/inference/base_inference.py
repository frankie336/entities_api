import abc
import base64
import inspect
import json
import logging
import mimetypes
import os
import pprint
import re
import threading
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable, Dict, Generator, List, Optional

import httpx
from fastapi import Depends
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
from projectdavid_common.schemas.enums import StatusEnum
from redis import Redis
from together import Together

from src.api.entities_api.constants.assistant import (
    CODE_ANALYSIS_TOOL_MESSAGE, CODE_INTERPRETER_MESSAGE,
    DEFAULT_REMINDER_MESSAGE, PLATFORM_TOOLS,
    WEB_SEARCH_PRESENTATION_FOLLOW_UP_INSTRUCTIONS)
from src.api.entities_api.constants.platform import (
    ERROR_NO_CONTENT, SPECIAL_CASE_TOOL_HANDLING)
from src.api.entities_api.dependencies import get_assistant_cache
from src.api.entities_api.ptool_handlers.code_interpreter.code_execution_client import \
    StreamOutput
from src.api.entities_api.ptool_handlers.platform_tool_service import \
    PlatformToolService
from src.api.entities_api.services.cached_assistant import AssistantCache
from src.api.entities_api.services.conversation_truncator import \
    ConversationTruncator
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = logging.getLogger(__name__)
SURFACE_TRACEBACK = os.getenv("SURFACE_TRACEBACK", "false").lower() == "true"
logging_utility = LoggingUtility()
validator = ValidationInterface()


class MissingParameterError(ValueError):
    """Specialized error for missing service parameters"""


class ConfigurationError(RuntimeError):
    """Error for invalid service configurations"""


class AuthenticationError(PermissionError):
    """Error for credential-related issues"""


class BaseInference(ABC):
    REASONING_PATTERN = re.compile("(<think>|</think>)")
    FC_REGEX = re.compile(
        "<fc>\\s*(?P<payload>\\{.*?\\})\\s*</fc>", re.DOTALL | re.IGNORECASE
    )

    def __init__(
        self,
        *,
        redis: Redis,
        base_url=os.getenv("BASE_URL"),
        api_key=None,
        assistant_id=None,
        thread_id=None,
        model_name="deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
        max_context_window=128000,
        threshold_percentage=0.8,
        available_functions=None,
        assistant_cache: AssistantCache = Depends(get_assistant_cache),
    ):
        self.assistant_cache = assistant_cache
        self.redis = redis
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
        try:
            self.together_client = Together(api_key=os.getenv("TOGETHER_API_KEY"))
        except Exception as e:
            logging_utility.error(
                "Failed to initialize default OpenAI client: %s", e, exc_info=True
            )
            self.openai_client = None
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
                api_key=project_david_api_key, base_url=project_david_base_url
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
            self.project_david_client = None
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
                return Together(api_key=api_key)
            except Exception as e:
                logging_utility.error(
                    "Failed to create specific TogetherAI client: %s", e, exc_info=True
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
        elif self.together_client:
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
                return Entity(api_key=api_key, base_url=base_url)
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
        elif self.project_david_client:
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
        elif self.openai_client:
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

    def set_assistant_id(self, assistant_id):
        if self.assistant_id != assistant_id:
            self._invalidate_service_cache(PlatformToolService)
            self.assistant_id = assistant_id

    def set_thread_id(self, thread_id):
        if self.thread_id != thread_id:
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
            '\n            \\{\\s*[\'"]name[\'"]\\s*:\\s*[\'"]code_interpreter[\'"]\\s*,\\s*   # "name": "code_interpreter"\n            [\'"]arguments[\'"]\\s*:\\s*\\{\\s*[\'"]code[\'"]\\s*:\\s*             # "arguments": {"code":\n            (?P<code>.*)                                               # Capture the rest as code content\n        ',
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
            "\n            \\{\\s*                                                      # Opening brace of outer object\n            (?P<q1>[\"']) (?P<first_key> [^\"']+?) (?P=q1) \\s* : \\s*      # First key\n            (?P<q2>[\"']) (?P<first_value> [^\"']+?) (?P=q2) \\s* , \\s*    # First value\n            (?P<q3>[\"']) (?P<second_key> [^\"']+?) (?P=q3) \\s* : \\s*     # Second key\n            \\{\\s*                                                      # Opening brace of nested object\n            (?P<q4>[\"']) (?P<nested_key> [^\"']+?) (?P=q4) \\s* : \\s*     # Nested key\n            (?P<q5>[\"']) (?P<nested_value> .*?) (?P=q5) \\s*             # Nested value (multiline allowed)\n            } \\s*                                                     # Closing brace of nested object\n            } \\s*                                                     # Closing brace of outer object\n        ",
            re.VERBOSE | re.DOTALL,
        )
        match = pattern.search(text)
        if match:
            return {
                "first_key": match.group("first_key"),
                "first_value": match.group("first_value"),
                "second_key": match.group("second_key"),
                "nested_key": match.group("nested_key"),
                "nested_value": match.group("nested_value").strip(),
            }
        else:
            return None

    def convert_smart_quotes(self, text: str) -> str:
        replacements = {"‘": "'", "’": "'", "“": '"', "”": '"'}
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
            if not isinstance(json_data, dict):
                return False
            if {"name", "arguments"} - json_data.keys():
                return False
            if not isinstance(json_data["name"], str) or not json_data["name"].strip():
                return False
            if not isinstance(json_data["arguments"], dict):
                return False
            for key, value in json_data["arguments"].items():
                if not isinstance(key, str):
                    return False
                if isinstance(value, (list, dict)):
                    return False
            return True
        except (TypeError, KeyError):
            return False

    def is_complex_vector_search(self, data: dict) -> bool:
        """Recursively validate operators with $ prefix"""
        for key, value in data.items():
            if key.startswith("$"):
                if isinstance(value, dict) and (
                    not self.is_complex_vector_search(value)
                ):
                    return False
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and (
                            not self.is_complex_vector_search(item)
                        ):
                            return False
            elif isinstance(value, dict):
                if not self.is_complex_vector_search(value):
                    return False
            elif isinstance(value, list):
                return False
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
        pattern = "\n            \\{                      # Opening curly brace\n            \\s*                     # Optional whitespace\n            ([\"'])name\\1\\s*:\\s*     # 'name' key with quotes\n            ([\"'])(.*?)\\2\\s*,\\s*    # Capture tool name\n            ([\"'])arguments\\4\\s*:\\s* # 'arguments' key\n            (\\{.*?\\})               # Capture arguments object\n            \\s*\\}                   # Closing curly brace\n        "
        candidates = []
        try:
            matches = re.finditer(pattern, text, re.DOTALL | re.VERBOSE)
            for match in matches:
                candidate = match.group(0)
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
        text = re.sub("```(?:json)?(.*?)```", "\\1", text, flags=re.DOTALL)
        text = re.sub("[“”]", '"', text)
        text = re.sub("(\\s|\\\\n)+", " ", text)
        pattern = '\n            \\{         # Opening curly brace\n            .*?        # Any characters\n            "name"\\s*:\\s*"(?P<name>[^"]+)"\n            .*?        # Any characters\n            "arguments"\\s*:\\s*\\{(?P<args>.*?)\\}\n            .*?        # Any characters\n            \\}         # Closing curly brace\n        '
        tool_matches = []
        for match in re.finditer(pattern, text, re.DOTALL | re.VERBOSE):
            try:
                raw_json = match.group()
                parsed = json.loads(raw_json)
                if not all((key in parsed for key in ["name", "arguments"])):
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
        - JSON strings that are escaped within an outer string (e.g., '"{"key": "value"}"').
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
        original_text_for_logging = text[:200] + ("..." if len(text) > 200 else "")
        processed_text = text.strip()
        parsed_json = None
        try:
            intermediate_parse = json.loads(processed_text)
            if isinstance(intermediate_parse, dict):
                logging_utility.debug("Direct JSON parse successful.")
                parsed_json = intermediate_parse
            elif isinstance(intermediate_parse, str):
                logging_utility.warning(
                    "Initial parse resulted in string, attempting inner JSON parse."
                )
                processed_text = intermediate_parse
            else:
                logging_utility.error(
                    f"Direct JSON parse resulted in unexpected type: {type(intermediate_parse)}. Expected dict or escaped string."
                )
                return False
        except json.JSONDecodeError:
            logging_utility.debug(
                "Direct/Unescaping parse failed. Proceeding to fixes."
            )
            pass
        except Exception as e:
            logging_utility.error(
                f"Unexpected error during initial JSON parse stage: {e}. Text: {original_text_for_logging}",
                exc_info=True,
            )
            return False
        if parsed_json and isinstance(parsed_json, dict):
            logging_utility.debug(
                "JSON already parsed, skipping fix stage (commas assumed handled or valid)."
            )
            pass
        else:
            try:
                if "'" in processed_text and '"' not in processed_text.replace(
                    "\\'", ""
                ):
                    logging_utility.warning(
                        f"Attempting single quote fix on: {processed_text[:100]}..."
                    )
                    fixed_text = processed_text.replace("'", '"')
                else:
                    fixed_text = processed_text
                fixed_text = re.sub(",(\\s*[}\\]])", "\\1", fixed_text)
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
        if isinstance(parsed_json, dict):
            return parsed_json
        else:
            logging_utility.error(
                "Final check failed: parsed_json is not a dictionary."
            )
            return False

    def normalize_content(self, content):
        """Smart format normalization with fallback."""
        try:
            if isinstance(content, dict):
                return content
            else:
                validated = self.ensure_valid_json(str(content))
                return validated if validated is not False else False
        except Exception as e:
            logging_utility.warning(f"Normalization failed: {str(e)}")
            return content

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
        vector_stores = self.vector_store_service.get_vector_stores_for_assistant(
            assistant_id=assistant_id
        )
        vector_store_mapping = {vs.name: vs.collection_name for vs in vector_stores}
        return vector_store_mapping[f"{assistant_id}-{store_suffix}"]

    def start_cancellation_listener(
        self, run_id: str, poll_interval: float = 1.0
    ) -> None:
        """
        Starts a background thread to listen for cancellation events.
        Only starts if it hasn't already been started.
        """
        from src.api.entities_api.services.event_handler import \
            EntitiesEventHandler

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

    def _process_tool_calls(
        self,
        thread_id: str,
        assistant_id: str,
        content: Dict[str, Any],
        run_id: str,
        api_key: str,
        poll_interval: float = 1.0,
        max_wait: float = 60.0,
    ) -> Dict[str, Any]:
        action = self.action_client.create_action(
            tool_name=content["name"], run_id=run_id, function_args=content["arguments"]
        )
        logging_utility.debug(
            "Created action %s for tool %s", action.id, content["name"]
        )
        pd_client = self._get_project_david_client(
            api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
        )
        runs_client = pd_client.runs
        runs_client.update_run_status(
            run_id=run_id, new_status=validator.StatusEnum.pending_action.value
        )
        logging_utility.info(f"Run {run_id} status updated to action_required")
        start = time.time()
        while True:
            pending = self.action_client.get_pending_actions(run_id)
            if not pending:
                break
            run = runs_client.retrieve_run(run_id)
            if run.status not in (StatusEnum.pending_action.value,):
                break
            if time.time() - start > max_wait:
                logging_utility.warning(
                    f"Timeout waiting for action {action.id} on run {run_id}"
                )
                break
            time.sleep(poll_interval)
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
            action = self.action_client.create_action(
                tool_name=content["name"],
                run_id=run_id,
                function_args=content["arguments"],
            )
            logging_utility.debug(
                "Created action %s for tool %s", action.id, content["name"]
            )
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
            platform_tool_service = self.platform_tool_service
            function_output = platform_tool_service.call_function(
                function_name=content["name"], arguments=content["arguments"]
            )
            logging_utility.debug(
                "Tool %s executed successfully for run %s", content["name"], run_id
            )
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
            raise

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
            client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )
            client.messages.submit_tool_output(
                thread_id=thread_id,
                content=f"ERROR: {str(e)}",
                role="tool",
                assistant_id=assistant_id,
                tool_id="dummy",
            )
            self.action_client.update_action(action_id=action.id, status="failed")
            raise

    def _handle_file_search(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        arguments_dict: Dict[str, Any],
    ) -> None:
        """
        Execute a file‑search tool call, pull out the assistant‑crafted
        summary (with citations) from the envelope, and post it back
        untouched. If something explodes, surface a readable error block
        to the assistant instead of crashing the stream.
        """
        ts_start = time.perf_counter()
        action = self.action_client.create_action(
            tool_name="file_search", run_id=run_id, function_args=arguments_dict
        )
        LOG.debug(
            "[%s] Created action id=%s args=%s",
            run_id,
            action.id,
            json.dumps(arguments_dict, indent=2),
        )
        try:
            query_text: str = arguments_dict["query_text"]
            vector_store_id = "vect_vsnpCIHB71ilrpKz8BkgmF"
            LOG.debug(
                "[%s] file_search → store=%s  query=%s",
                run_id,
                vector_store_id,
                query_text,
            )
            pd_client = self._get_project_david_client(
                api_key=os.getenv("ADMIN_API_KEY"), base_url=os.getenv("BASE_URL")
            )
            search_envelope = pd_client.vectors.file_search(
                vector_store_id=vector_store_id,
                query_text=query_text,
                vector_store_host="qdrant",
            )
            LOG.debug(
                "[%s] file_search raw‑envelope (%d\u202fbytes)",
                run_id,
                len(json.dumps(search_envelope)),
            )
            extracted: List[Dict[str, Any]] = [
                {"text": c.get("text", ""), "annotations": c.get("annotations", [])}
                for item in search_envelope.get("output", [])
                if item.get("type") == "message"
                for c in item.get("content", [])
                if c.get("type") == "output_text"
            ]
            if not extracted:
                raise RuntimeError(
                    "No `output_text` blocks found in file‑search envelope"
                )
            LOG.debug("[%s] extracted %d blocks", run_id, len(extracted))
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=json.dumps(extracted, indent=2),
                action=action,
            )
            self.action_client.update_action(action_id=action.id, status="completed")
            LOG.info(
                "[%s] file_search completed in %.2fs (action=%s)",
                run_id,
                time.perf_counter() - ts_start,
                action.id,
            )
        except Exception as exc:
            tb = traceback.format_exc()
            LOG.error(
                "[%s] file_search FAILED action=%s  exc=%s\n%s",
                run_id,
                action.id,
                exc,
                tb,
            )
            self.action_client.update_action(action_id=action.id, status="failed")
            err_block = {"error_type": exc.__class__.__name__, "message": str(exc)}
            if isinstance(exc, httpx.HTTPStatusError):
                err_block.update(
                    {
                        "status_code": exc.response.status_code,
                        "response_text": exc.response.text,
                        "url": str(exc.request.url),
                    }
                )
            if SURFACE_TRACEBACK:
                err_block["traceback"] = tb
            try:
                self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=json.dumps(err_block, indent=2),
                    action=action,
                )
            except Exception as inner:
                LOG.exception(
                    "[%s] Failed to surface error to assistant: %s", run_id, inner
                )
            raise

    def handle_code_interpreter_action(
        self, thread_id, run_id, assistant_id, arguments_dict
    ):
        action = self.action_client.create_action(
            tool_name="code_interpreter", run_id=run_id, function_args=arguments_dict
        )
        code = arguments_dict.get("code")
        uploaded_files = []
        hot_code_buffer = []
        final_content_for_assistant = ""
        logging_utility.info("Starting code execution streaming...")
        try:
            execution_chunks = []
            for chunk_str in self.code_execution_client.stream_output(code):
                execution_chunks.append(chunk_str)
            for chunk_str in execution_chunks:
                try:
                    parsed_wrapper = json.loads(chunk_str)
                    if "stream_type" in parsed_wrapper and "chunk" in parsed_wrapper:
                        parsed = parsed_wrapper["chunk"]
                        yield chunk_str
                    else:
                        parsed = parsed_wrapper
                        yield json.dumps(
                            {"stream_type": "code_execution", "chunk": parsed}
                        )
                    chunk_type = parsed.get("type")
                    content = parsed.get("content")
                    if chunk_type == "status":
                        status = content
                        logging_utility.debug("Status chunk: %s", status)
                        if status == "complete" and "uploaded_files" in parsed:
                            uploaded_files.extend(parsed.get("uploaded_files", []))
                            logging_utility.info(
                                "Execution complete; files metadata: %s",
                                parsed.get("uploaded_files", []),
                            )
                        elif status == "process_complete":
                            logging_utility.info(
                                "Process completed with exit code: %s",
                                parsed.get("exit_code"),
                            )
                    elif chunk_type == "hot_code_output":
                        hot_code_buffer.append(content)
                    elif chunk_type == "error":
                        logging_utility.error(
                            "Error chunk during execution: %s", content
                        )
                        hot_code_buffer.append(f"[Code Execution Error: {content}]")
                except json.JSONDecodeError:
                    logging_utility.error("Invalid JSON chunk: %s", chunk_str)
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
                        "Error processing execution chunk: %s – %s",
                        str(e),
                        chunk_str,
                        exc_info=True,
                    )
                    yield json.dumps(
                        {
                            "stream_type": "code_execution",
                            "chunk": {
                                "type": "error",
                                "content": f"Internal error: {str(e)}",
                            },
                        }
                    )
        except Exception as stream_err:
            logging_utility.error("Streaming error: %s", str(stream_err), exc_info=True)
            yield json.dumps(
                {
                    "stream_type": "code_execution",
                    "chunk": {
                        "type": "error",
                        "content": f"Failed to stream code execution: {str(stream_err)}",
                    },
                }
            )
            uploaded_files = []
        logging_utility.info("Building final content from code output buffer...")
        if hot_code_buffer:
            final_content_for_assistant = "\n".join(hot_code_buffer).strip()
        else:
            final_content_for_assistant = "[Code executed successfully, no output.]"
        if uploaded_files:
            logging_utility.info(
                "Streaming base64 previews for %d files...", len(uploaded_files)
            )
            for file_meta in uploaded_files:
                file_id = file_meta.get("id")
                filename = file_meta.get("filename")
                if not file_id or not filename:
                    continue
                guessed_mime, _ = mimetypes.guess_type(filename)
                mime_type = guessed_mime or "application/octet-stream"
                try:
                    b64 = self.files.get_file_as_base64(file_id=file_id)
                except Exception as e:
                    logging_utility.error(
                        "Error fetching base64 for %s: %s",
                        filename,
                        str(e),
                        exc_info=True,
                    )
                    b64 = base64.b64encode(
                        f"Error retrieving content: {str(e)}".encode()
                    ).decode()
                    mime_type = "text/plain"
                yield json.dumps(
                    {
                        "stream_type": "code_execution",
                        "chunk": {
                            "type": "code_interpreter_stream",
                            "content": {
                                "filename": filename,
                                "file_id": file_id,
                                "base64": b64,
                                "mime_type": mime_type,
                            },
                        },
                    }
                )
        logging_utility.info("Yielding final content chunk.")
        yield json.dumps(
            {
                "stream_type": "code_execution",
                "chunk": {"type": "content", "content": final_content_for_assistant},
            }
        )
        logging_utility.info(
            "Final uploaded_files metadata:\n%s", pprint.pformat(uploaded_files)
        )
        try:
            logging_utility.info("Submitting text-only output to assistant.")
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=final_content_for_assistant,
                action=action,
            )
            logging_utility.info("Tool output submitted successfully.")
        except Exception as submit_err:
            logging_utility.error(
                "Error submitting tool output: %s", str(submit_err), exc_info=True
            )
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

        from src.api.entities_api.ptool_handlers.computer.shell_command_interface import \
            run_shell_commands

        action = self.action_client.create_action(
            tool_name="computer", run_id=run_id, function_args=arguments_dict
        )
        commands = arguments_dict.get("commands", [])
        accumulated_content = ""
        for chunk in run_shell_commands(commands, thread_id=thread_id):
            try:
                accumulated_content += chunk
                yield chunk
            except json.JSONDecodeError:
                error_message = "Error: Invalid JSON chunk received from computer command execution."
                self.submit_tool_output(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=error_message,
                    action=action,
                )
                raise RuntimeError(error_message)
        if not accumulated_content:
            error_message = "Error: No computer output was generated. The command may have failed or produced no output."
            self.submit_tool_output(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=error_message,
                action=action,
            )
            raise RuntimeError(error_message)
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
        reminder = (
            CODE_INTERPRETER_MESSAGE
            if name == "code_interpreter"
            else DEFAULT_REMINDER_MESSAGE
        )
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
                    yield (json.dumps({"type": "content", "content": content}) + "\n")
                elif chunk_type == "error":
                    logging_utility.error("Error in assistant stream: %s", content)
                    yield json.dumps({"type": "error", "content": content})
                    return
                else:
                    yield json.dumps(parsed)
                time.sleep(0.01)
        except Exception as e:
            error_msg = f"[ERROR] Hyperbolic stream failed: {str(e)}"
            logging_utility.error(error_msg, exc_info=True)
            yield json.dumps({"type": "error", "content": error_msg})
            return
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
        if "\n" in code_buffer:
            newline_pos = code_buffer.find("\n") + 1
            line_chunk = code_buffer[:newline_pos]
            code_buffer = code_buffer[newline_pos:]
            results.append(json.dumps({"type": "hot_code", "content": line_chunk}))
        if len(code_buffer) > 100:
            results.append(json.dumps({"type": "hot_code", "content": code_buffer}))
            code_buffer = ""
        return (results, code_buffer)

    def _shunt_to_redis_stream(
        self, redis, stream_key, chunk_dict, *, maxlen=1000, ttl_seconds=3600
    ):
        try:
            if isinstance(chunk_dict, str):
                chunk_dict = json.loads(chunk_dict)
            redis.xadd(stream_key, chunk_dict, maxlen=maxlen, approximate=True)
            if not redis.exists(f"{stream_key}::ttl_set"):
                redis.expire(stream_key, ttl_seconds)
                redis.set(f"{stream_key}::ttl_set", "1", ex=ttl_seconds)
        except Exception as e:
            logging_utility.warning(
                f"[Redis Shunt] Failed to XADD or EXPIRE {stream_key}: {e}",
                exc_info=True,
            )

    def _build_system_message(self, assistant_id: str):
        """
        Build the system‑prompt block:
        • pulls instructions/tools from Redis‑backed AssistantCache
        • injects the current timestamp
        """
        cfg = self.assistant_cache.retrieve_sync(assistant_id)
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "role": "system",
            "content": f"tools:\n{json.dumps(cfg['tools'])}\n{cfg['instructions']}\nToday's date and time: {today}",
        }

    def _set_up_context_window(
        self, assistant_id: str, thread_id: str, trunk: bool = True
    ):
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
        system_msg = self._build_system_message(assistant_id)
        redis_key = f"thread:{thread_id}:history"
        raw_list = self.redis.lrange(redis_key, 0, -1)
        if not raw_list:
            client = Entity(
                base_url=os.getenv("ASSISTANTS_BASE_URL"),
                api_key=os.getenv("ADMIN_API_KEY"),
            )
            full_hist = client.messages.get_formatted_messages(
                thread_id, system_message=system_msg["content"]
            )
            for msg in full_hist[-200:]:
                self.redis.rpush(redis_key, json.dumps(msg))
            self.redis.ltrim(redis_key, -200, -1)
            raw_list = [json.dumps(m) for m in full_hist]
        msgs = [system_msg] + [json.loads(x) for x in raw_list]
        normalized = self.normalize_roles(msgs)
        return self.conversation_truncator.truncate(normalized) if trunk else normalized

    def parse_and_set_function_calls(
        self, accumulated_content: str, assistant_reply: str
    ) -> Optional[Dict[str, Any]]:
        """
        Robustly locate a <fc>{...}</fc> JSON block *anywhere* in either
        accumulated_content or assistant_reply, even if split across chunks.
        """

        def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
            """Return parsed JSON if a <fc> block is found, else None."""
            match = self.FC_REGEX.search(text)
            if not match:
                return None
            raw_json = match.group("payload")
            parsed = self.ensure_valid_json(raw_json)
            if parsed and (
                self.is_valid_function_call_response(parsed)
                or self.is_complex_vector_search(parsed)
            ):
                return parsed
            return None

        parsed_fc = _extract_json_block(accumulated_content)
        if parsed_fc:
            self.set_tool_response_state(True)
            self.set_function_call_state(parsed_fc)
            logging_utility.debug("Function-call found in accumulated buffer.")
            return parsed_fc
        parsed_fc = _extract_json_block(assistant_reply)
        if parsed_fc and (not self.get_tool_response_state()):
            self.set_tool_response_state(True)
            self.set_function_call_state(parsed_fc)
            logging_utility.debug("Embedded Function-call found in assistant reply.")
            return parsed_fc
        if not parsed_fc:
            embedded = self.extract_function_calls_within_body_of_text(assistant_reply)
            if embedded:
                self.set_tool_response_state(True)
                self.set_function_call_state(embedded[0])
                logging_utility.debug("Legacy JSON pattern detected.")
                return embedded[0]
        return None

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
        elif tool_name == "file_search":
            self._handle_file_search(
                thread_id=thread_id,
                run_id=run_id,
                assistant_id=assistant_id,
                arguments_dict=arguments_dict,
            )
        elif tool_name in PLATFORM_TOOLS:
            if tool_name not in SPECIAL_CASE_TOOL_HANDLING:
                self._process_platform_tool_calls(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=fc_state,
                    run_id=run_id,
                )
            else:
                self._process_tool_calls(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    content=fc_state,
                    run_id=run_id,
                    api_key=api_key,
                )
        else:
            self._process_tool_calls(
                thread_id=thread_id,
                assistant_id=assistant_id,
                content=fc_state,
                run_id=run_id,
                api_key=api_key,
            )

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
