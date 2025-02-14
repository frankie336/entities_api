from entities_api.platform_tools.code_interpreter_handler import CodeExecutionHandler
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class PlatformToolService:
    def __init__(self):
        self.code_execution_handler = CodeExecutionHandler()

        # Store the handler itself, not the method call
        self.function_handlers = {
            "code_interpreter": self.code_execution_handler.execute_code,
        }

    def call_function(self, function_name, arguments):
        print('ONE SMALL STEP FOR MAN, ONE GIANT LEAP FOR MANKIND')
        if function_name not in self.function_handlers:
            logging_utility.error("Unsupported function: %s", function_name)
            return "Error: Unsupported function"

        # Extract and pass the required arguments to the handler
        return self.function_handlers[function_name](
            code=arguments.get("code", ""),
            language=arguments.get("language", "python"),
            user_id=arguments.get("user_id", "test_user")
        )