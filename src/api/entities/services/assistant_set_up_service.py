# entities/services/assistant_setup_service.py

from entities_common import ValidationInterface

from entities import EntitiesInternalInterface
from entities.constants.assistant import DEFAULT_MODEL, BASE_ASSISTANT_INSTRUCTIONS, BASE_TOOLS
from entities.services.logging_service import LoggingUtility

validate = ValidationInterface()



from entities.services.vector_store_service import VectorStoreService
from entities.services.vector_waves import AssistantVectorWaves


class AssistantSetupService:
    def __init__(self):
        self.client = EntitiesInternalInterface()
        self.logging_utility = LoggingUtility()
        self.vector_store_service = VectorStoreService()
        self._vector_waves = None  # Lazy initialization holder

    @property
    def vector_waves(self):
        """Lazy-loaded vector waves component"""
        if self._vector_waves is None:
            self._vector_waves = AssistantVectorWaves(
                vector_service=self.vector_store_service
            )
        return self._vector_waves

    def create_and_associate_tools(self, function_definitions, assistant_id):
        """Batch-friendly tool creation with error handling"""
        for func_def in function_definitions:
            try:
                tool_name = func_def['function']['name']

                tool_function = validate.ToolFunction(function=func_def)

                new_tool = self.client.tool_service.create_tool(
                    name=tool_name,
                    type='function',
                    function=tool_function.model_dump(),
                    assistant_id=assistant_id
                )

                self.client.tool_service.associate_tool_with_assistant(
                    tool_id=new_tool.id,
                    assistant_id=assistant_id
                )

                self.logging_utility.info(
                    "Created tool: %s (ID: %s)",
                    tool_name,
                    new_tool.id
                )

            except Exception as e:
                self.logging_utility.error(
                    "Tool creation failed for %s: %s",
                    tool_name,
                    str(e)
                )
                raise

    def setup_assistant_with_tools(self, user_id, assistant_name, assistant_description,
                                   model, instructions, function_definitions):
        """Streamlined setup with pre-validated user ID"""
        try:

            assistant = self.client.assistant_service.create_assistant(
                name=assistant_name,
                description=assistant_description,
                model=model,
                instructions=instructions,
                assistant_id="default",
                tools=[{"type":"code_interpreter"}]


            )


            self.logging_utility.info(
                "Created assistant: %s (ID: %s)",
                assistant_name,
                assistant.id
            )

            self.create_and_associate_tools(function_definitions, assistant.id)

            return assistant

        except Exception as e:
            self.logging_utility.error(
                "Assistant setup failed: %s",
                str(e)
            )
            raise

    def orchestrate_default_assistant(self):
        """Optimized main flow with single user creation"""
        try:
            # Get or create pattern prevents duplicate users
            user = self.client.user_service.create_user(name="default")

            self.logging_utility.debug(
                "Using existing user: ID %s",
                user.id
            )

            assistant = self.setup_assistant_with_tools(
                user_id=user.id,
                assistant_name='Q',
                assistant_description='Assistant',
                model=DEFAULT_MODEL,
                instructions=BASE_ASSISTANT_INSTRUCTIONS,
                function_definitions=BASE_TOOLS
            )

            # Deferred initialization of vector waves
            self.vector_waves._initialize_core_waves(
                user_id=user.id,
                assistant_id=assistant.id
            )

            self.logging_utility.info(
                "Setup completed. Assistant ID: %s",
                assistant.id
            )
            return assistant

        except Exception as e:
            self.logging_utility.critical(
                "Critical failure in orchestration: %s",
                str(e)
            )
            raise


# Example usage remains unchanged
if __name__ == "__main__":
    service = AssistantSetupService()
    #service.create_and_associate_tools(function_definitions=BASE_TOOLS,assistant_id='default')
    service.orchestrate_default_assistant()