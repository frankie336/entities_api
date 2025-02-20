import time
from functools import lru_cache
import threading
from entities_api.platform_tools.code_interpreter_handler import CodeExecutionHandler
from entities_api.platform_tools.web_search_handler import FirecrawlService
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()


class PlatformToolService:
    # Class-level cache for function handlers
    function_handlers = {
        "code_interpreter": None,  # Placeholder for lazy initialization
        "web_search": None,
        # Add more handlers here as needed
    }


    def __init__(self, base_url=None, api_key=None):
        # Lazy initialization of handlers
        self._code_execution_handler = None
        self._web_search_handler = None

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


    def call_function(self, function_name, arguments):
        """
        Executes a function based on the provided name and arguments.
        Caches results to avoid redundant computations.
        """
        # Create a cache key from function name and arguments
        cache_key = (function_name, frozenset(arguments.items()))

        # Check if the result is already cached
        with self._cache_lock:
            if cache_key in self._call_cache:
                logging_utility.info("Returning cached result for function: %s", function_name)
                return self._call_cache[cache_key]

        # Validate if the function is supported
        if function_name not in self.function_handlers:
            logging_utility.error("Unsupported function: %s", function_name)
            return "Error: Unsupported function"

        # Lazy initialization of the handler if not already initialized
        if self.function_handlers[function_name] is None:
            if function_name == "code_interpreter":
                self.function_handlers[function_name] = self._get_code_execution_handler().execute_code

            if function_name == "web_search":

                self.function_handlers[function_name] = self._get_web_search_handler().search_orchestrator

            # Add more handlers here as needed

        # Get the handler
        handler = self.function_handlers[function_name]

        # Execute the function and cache the result
        # Pass all arguments dynamically using **kwargs
        result = handler(**arguments)

        with self._cache_lock:
            self._call_cache[cache_key] = result

        logging_utility.info("Function %s executed and result cached.", function_name)
        return result