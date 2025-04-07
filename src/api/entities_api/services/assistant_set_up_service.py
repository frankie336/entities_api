# entities_api/services/assistant_setup_service.py

from entities_common import ValidationInterface
from entities import Entities

from entities_api.constants.assistant import DEFAULT_MODEL, BASE_ASSISTANT_INSTRUCTIONS, BASE_TOOLS
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.vector_store_service import VectorStoreService
from entities_api.services.vector_waves import AssistantVectorWaves

validate = ValidationInterface()


class AssistantSetupService:
    def __init__(self):
        self.client = Entities()
        self.logging_utility = LoggingUtility()
        self.vector_store_service = VectorStoreService()
        self._vector_waves = None  # Lazy initialization holder

    @property
    def vector_waves(self):
        """Lazy-loaded vector waves component"""
        if self._vector_waves is None:
            self._vector_waves = AssistantVectorWaves(vector_service=self.vector_store_service)
        return self._vector_waves

    def create_and_associate_tools(self, function_definitions, assistant_id):
        """Creates tools if they do not already exist and associates them with the assistant."""
        for func_def in function_definitions:
            tool_name = func_def["function"]["name"]
            try:
                # Attempt to retrieve an existing tool for this assistant
                existing_tool = self.client.tools.get_tool_by_name(tool_name)
                if existing_tool:
                    self.logging_utility.info("Tool already exists: %s (ID: %s)", tool_name,
                                              existing_tool.id)
                    continue  # Skip creation if tool exists
            except Exception as retrieval_error:
                self.logging_utility.debug("No existing tool found for %s: %s", tool_name,
                                           str(retrieval_error))

            try:
                tool_function = validate.ToolFunction(function=func_def)
                new_tool = self.client.tools.create_tool(
                    name=tool_name,
                    type="function",
                    function=tool_function.model_dump(),
                    assistant_id=assistant_id,
                )
                self.client.tools.associate_tool_with_assistant(
                    tool_id=new_tool.id, assistant_id=assistant_id
                )
                self.logging_utility.info("Created tool: %s (ID: %s)", tool_name, new_tool.id)
            except Exception as e:
                self.logging_utility.error("Tool creation failed for %s: %s", tool_name, str(e))
                # Optionally, continue to the next tool instead of raising the exception.
                continue

    def setup_assistant_with_tools(
        self,
        user_id,
        assistant_name,
        assistant_description,
        model,
        instructions,
        function_definitions,
    ):
        """Gets an existing default assistant if it exists; otherwise, creates one, then sets up tools."""
        try:
            # Attempt to retrieve the default assistant
            assistant = self.client.assistants.retrieve_assistant("default")
            self.logging_utility.info("Default assistant already exists: %s", assistant.id)
        except Exception:
            # If retrieval fails (assistant not found), create a new one.
            try:
                assistant = self.client.assistants.create_assistant(
                    name=assistant_name,
                    description=assistant_description,
                    model=model,
                    instructions=instructions,
                    assistant_id="default",
                )
                self.logging_utility.info("Created new default assistant: %s (ID: %s)",
                                          assistant_name, assistant.id)
            except Exception as e:
                self.logging_utility.error("Assistant creation failed: %s", str(e))
                raise

        # Now, create and associate tools (existing tools will be skipped)
        self.create_and_associate_tools(function_definitions, assistant.id)
        return assistant

    def orchestrate_default_assistant(self):
        """Main orchestration flow for setting up the default assistant for a user."""
        try:
            # Use a get-or-create approach for the default user
            try:
                user = self.client.users.retrieve_user("default")
                self.logging_utility.debug("Using existing user: ID %s", user.id)
            except Exception:
                user = self.client.users.create_user(name="default")
                self.logging_utility.info("Created default user: ID %s", user.id)

            assistant = self.setup_assistant_with_tools(
                user_id=user.id,
                assistant_name="Q",
                assistant_description="Assistant",
                model=DEFAULT_MODEL,
                instructions=BASE_ASSISTANT_INSTRUCTIONS,
                function_definitions=BASE_TOOLS,
            )

            self.logging_utility.info("Setup completed. Assistant ID: %s", assistant.id)
            return assistant

        except Exception as e:
            self.logging_utility.critical("Critical failure in orchestration: %s", str(e))
            raise


# Example usage remains unchanged
if __name__ == "__main__":
    service = AssistantSetupService()
    service.orchestrate_default_assistant()
