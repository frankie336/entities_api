from entities_api.clients.client import OllamaClient
from entities_api.schemas import ToolFunction  # Import ToolFunction
from entities_api.constants.assistant import DEFAULT_MODEL, BASE_ASSISTANT_INSTRUCTIONS, BASE_TOOLS
from entities_api.services.logging_service import LoggingUtility

class AssistantSetupService:
    def __init__(self):
        self.client = OllamaClient()
        self.logging_utility = LoggingUtility()

    def create_and_associate_tools(self, function_definitions, assistant_id):
        for func_def in function_definitions:
            tool_name = func_def['function']['name']
            tool_function = ToolFunction(function=func_def['function'])
            new_tool = self.client.tool_service.create_tool(
                name=tool_name,
                type='function',
                function=tool_function,
                assistant_id=assistant_id
            )
            self.client.tool_service.associate_tool_with_assistant(
                tool_id=new_tool.id,
                assistant_id=assistant_id
            )
            self.logging_utility.info("New tool created: Name: %s, ID: %s", tool_name, new_tool.id)
            self.logging_utility.debug("Tool details: %s", new_tool)

    def setup_assistant_with_tools(self, user_name, assistant_name, assistant_description,
                                   model, instructions, function_definitions):
        try:
            user = self.client.user_service.create_user(name=user_name)
            self.logging_utility.info("User created: ID: %s", user.id)
        except Exception as e:
            self.logging_utility.error("Error creating user: %s", str(e))
            raise

        try:
            assistant = self.client.assistant_service.create_assistant(
                name=assistant_name,
                description=assistant_description,
                model=model,
                instructions=instructions,
                assistant_id="default"
            )
            self.logging_utility.info("Assistant created: ID: %s", assistant.id)
        except Exception as e:
            self.logging_utility.error("Error creating assistant: %s", str(e))
            raise

        try:
            self.create_and_associate_tools(function_definitions, assistant.id)
        except Exception as e:
            self.logging_utility.error("Error creating and associating tools: %s", str(e))
            raise

        return assistant

    def assistant_orchestrator(self):

        assistant = self.setup_assistant_with_tools(
            user_name='default',
            assistant_name='Nexa',
            assistant_description='Assistant',
            model=DEFAULT_MODEL,
            instructions=BASE_ASSISTANT_INSTRUCTIONS,
            function_definitions=BASE_TOOLS
        )
        self.logging_utility.info("Setup complete. Assistant ID: %s", assistant.id)


# Example usage
if __name__ == "__main__":
    service = AssistantSetupService()
    assistant = service.setup_assistant_with_tools(
        user_name='default',
        assistant_name='Nexa',
        assistant_description='Assistant',
        model=DEFAULT_MODEL,
        instructions=BASE_ASSISTANT_INSTRUCTIONS,
        function_definitions=BASE_TOOLS
    )
    service.logging_utility.info("Setup complete. Assistant ID: %s", assistant.id)
