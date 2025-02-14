from entities_api.platform_tools.code_interpreter_handler import CodeExecutionHandler
from entities_api.services.logging_service import LoggingUtility

logging_utility = LoggingUtility()

class PlatformToolService:
    def __init__(self):

        self.conde_execution_handler = CodeExecutionHandler()

        self.function_handlers = {
            "code_interpreter": self.conde_execution_handler,

        }

    def call_function(self, function_name, arguments):


        if function_name not in self.function_handlers:
            logging_utility.error("Unsupported function: %s", function_name)
            return "Error: Unsupported function"

        return self.function_handlers[function_name](arguments)

