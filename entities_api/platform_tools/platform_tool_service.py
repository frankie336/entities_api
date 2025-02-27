import time
from functools import lru_cache
import threading
from entities_api.platform_tools.code_interpreter_handler import CodeExecutionHandler
from entities_api.platform_tools.web_search_handler import FirecrawlService
from entities_api.platform_tools.vector_search_handler import VectorSearchHandler
from entities_api.services.logging_service import LoggingUtility


logging_utility = LoggingUtility()


class PlatformToolService:
    # Class-level cache for function handlers
    function_handlers = {
        "code_interpreter": None,  # Placeholder for lazy initialization
        "web_search": None,
        "vector_store_search": None
        # Add more handlers here as needed
    }


    def __init__(self, base_url=None, api_key=None, assistant_id=None):
        # Lazy initialization of handlers
        self._code_execution_handler = None
        self._web_search_handler = None
        self._vector_search_handler = None
        self.assistant_id = assistant_id

        # Cache for function call results
        self._call_cache = {}

        # Lock for thread-safe caching
        self._cache_lock = threading.Lock()

    def _get_code_execution_handler(self):
        """Lazy initialization of CodeExecutionHandler."""
        if self._code_execution_handler is None:
            self._code_execution_handler = CodeExecutionHandler()
        return self._code_execution_handler


    def _get_web_search_handler(self):
        """Lazy initialization of CodeExecutionHandler."""
        if self._web_search_handler is None:
            self._web_search_handler = FirecrawlService()
        return self._web_search_handler

    def _get_vector_search_handler(self):
        """Lazy initialization of CodeExecutionHandler."""
        if self._vector_search_handler is None:
            self._vector_search_handler = VectorSearchHandler(assistant_id=self.assistant_id)
        return self._vector_search_handler

    def call_function(self, function_name, arguments):
        """
        Executes a function based on the provided name and arguments.
        Caches results to avoid redundant computations.
        """
        if not isinstance(arguments, dict):
            logging_utility.error(
                "Invalid 'arguments' type: Expected dictionary but got %s", type(arguments)
            )
            return {"error": "Invalid arguments format. Expected a dictionary."}

        # Create a cache key from function name and arguments
        try:
            cache_key = (function_name, frozenset(arguments.items()))
        except TypeError as e:
            logging_utility.error("Failed to create cache key: %s", str(e))
            return {"error": "Arguments contain unhashable values."}

        # Check if the result is already cached
        with self._cache_lock:
            if cache_key in self._call_cache:
                logging_utility.info("Returning cached result for function: %s", function_name)
                return self._call_cache[cache_key]

        # Validate if the function is supported
        if function_name not in self.function_handlers:
            logging_utility.error("Unsupported function: %s", function_name)
            return {"error": f"Unsupported function: {function_name}"}

        # Lazy initialization of the handler if not already initialized
        if self.function_handlers[function_name] is None:
            if function_name == "code_interpreter":
                self.function_handlers[function_name] = self._get_code_execution_handler().execute_code

            elif function_name == "web_search":
                self.function_handlers[function_name] = self._get_web_search_handler().search_orchestrator

            elif function_name == "vector_store_search":
                self.function_handlers[function_name] = self._get_vector_search_handler().execute_search

            else:
                logging_utility.error("No handler available for function: %s", function_name)
                return {"error": f"No handler available for function: {function_name}"}

        # Get the handler
        handler = self.function_handlers[function_name]

        # Execute the function and cache the result
        try:
            result = handler(**arguments)
        except TypeError as e:
            logging_utility.error(
                "Error calling function '%s' with arguments %s: %s",
                function_name, arguments, str(e)
            )
            return {"error": f"Function '{function_name}' received incorrect arguments: {str(e)}"}

        with self._cache_lock:
            self._call_cache[cache_key] = result

        logging_utility.info("Function %s executed and result cached.", function_name)
        return result
