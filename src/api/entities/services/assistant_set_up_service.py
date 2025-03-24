from pathlib import Path
from dotenv import set_key

from entities.clients.client import OllamaClient
from entities.constants.assistant import DEFAULT_MODEL, BASE_ASSISTANT_INSTRUCTIONS, BASE_TOOLS
from entities.constants.platform import TOOLS_ID_MAP
from entities.schemas.tools import ToolFunction
from entities.services.logging_service import LoggingUtility
from entities.services.vector_store_service import VectorStoreService
from entities.services.vector_waves import AssistantVectorWaves

logging_utility = LoggingUtility()

class AssistantSetupService:
    def __init__(self):
        self.client = OllamaClient()
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

    def create_base_tools(self, function_definitions):
        """Batch-friendly tool creation with error handling."""
        client = OllamaClient()

        # Determine the project root and locate the .env file
        PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
        env_file_path = PROJECT_ROOT / ".env"  # Target the .env in the project root

        for func_def in function_definitions:
            try:
                # Extract the tool name from the function definition.
                raw_tool_name = func_def['function']['name']

                # Convert tool name to .env-friendly format.
                tool_name_env = f"TOOL_{raw_tool_name.upper().replace('-', '_').replace(' ', '_')}"

                # Create a ToolFunction instance from the function definition.
                tool_function = ToolFunction(function=func_def['function'])

                # Determine the tool type; if not provided, default to 'function'.
                tool_type = func_def.get('type', 'function')
                # If the tool type is in the mapping, use the mapped ID; otherwise, let the service generate one.
                set_id = TOOLS_ID_MAP.get(tool_type)

                # Create the tool; pass the optional set_id so that if present, it is used for the tool's ID.
                new_tool = self.client.tool_service.create_tool(
                    name=raw_tool_name,
                    type=tool_type,
                    function=tool_function,
                    set_id=set_id
                )

                # Update (or append) the .env file in the project root with the formatted environment-friendly name.
                set_key(str(env_file_path), tool_name_env, new_tool.id)
                self.logging_utility.info("Updated .env (%s): %s=%s", env_file_path, tool_name_env, new_tool.id)
                self.logging_utility.info(
                    "Created tool: %s (ID: %s) and stored as %s in .env",
                    raw_tool_name,
                    new_tool.id,
                    tool_name_env
                )

            except Exception as e:
                self.logging_utility.error("Tool creation failed for %s: %s", raw_tool_name, str(e))
                raise

    def setup_assistant_with_tools(self, user_id, assistant_name, assistant_description,
                                   model, instructions, function_definitions):
        """Streamlined setup with pre-validated user ID"""
        try:
            self.create_base_tools(function_definitions)

            assistant = self.client.assistant_service.create_assistant(
                assistant_id="default",
                name=assistant_name,
                description=assistant_description,
                model=model,
                instructions=instructions,
                tools=[
                    {"type": "code_interpreter"},
                    {"type": "web_search"},
                    {"type": "vector_store_search"},
                    {"type": "computer"}
                ]
            )


            print(assistant)


            assistant = self.client.assistant_service.retrieve_assistant(assistant_id=assistant.id)

            self.logging_utility.info(
                "Created assistant: %s (ID: %s)",
                assistant_name,
                assistant.id
            )

            return assistant

        except Exception as e:
            self.logging_utility.error("Assistant setup failed: %s", str(e))
            raise

    def orchestrate_default_assistant(self):
        """Optimized main flow with single user creation"""
        try:
            # Get or create pattern prevents duplicate users
            user = self.client.user_service.create_user(name="default")
            self.logging_utility.debug("Using existing user: ID %s", user.id)

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

            self.logging_utility.info("Setup completed. Assistant ID: %s", assistant.id)
            return assistant

        except Exception as e:
            self.logging_utility.critical("Critical failure in orchestration: %s", str(e))
            raise

if __name__ == "__main__":
    try:
        service = AssistantSetupService()
        service.orchestrate_default_assistant()
    except Exception as e:
        logging_utility.critical("Failed during orchestration: %s", str(e))
        raise
