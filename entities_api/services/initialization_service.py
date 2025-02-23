from typing import List, Dict

from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from tenacity import retry, stop_after_attempt, wait_fixed

from entities_api.clients.client import OllamaClient
from entities_api.constants.assistant import DEFAULT_MODEL, BASE_ASSISTANT_INSTRUCTIONS, BASE_TOOLS
from entities_api.schemas import ToolFunction, AssistantRead
from entities_api.services.logging_service import LoggingUtility
from entities_api.services.vector_waves import AssistantVectorWaves
from entities_api.constants.platform import DIRECT_DATABASE_URL

logging_utility = LoggingUtility()


class AssistantInitializationService:
    def __init__(self):
        self.client = OllamaClient()
        self._service_ready = False
        self.engine = create_engine(DIRECT_DATABASE_URL, echo=True)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    @retry(stop=stop_after_attempt(10), wait=wait_fixed(3))
    def _check_service_dependencies(self):
        """Validate all required services are operational"""
        # Check database connection
        try:
            with self.SessionLocal() as session:
                session.execute(text("SELECT 1"))
        except Exception as e:
            raise ConnectionError(f"Database connection failed: {str(e)}")

        # Check Qdrant health
        if not self.client.vector_service.health_check():
            raise ConnectionError("Vector store not ready")

    def initialize_core_assistant(self,
                                  user_name: str = "system",
                                  assistant_id: str = "default") -> AssistantRead:
        """Core initialization workflow matching original script functionality"""
        try:
            # 1. Service readiness check
            self._check_service_dependencies()

            # 2. Create system user (matches original script)
            user = self.client.user_service.create_user(name=user_name)
            logging_utility.info(f"User created: ID: {user.id}")

            # 3. Create assistant (identical to original)
            assistant = self.client.assistant_service.create_assistant(
                name="Nexa",
                description="Core AI Assistant",
                model=DEFAULT_MODEL,
                instructions=BASE_ASSISTANT_INSTRUCTIONS,
                assistant_id=assistant_id
            )
            logging_utility.info(f"Assistant created: ID: {assistant.id}")

            # 4. Create and associate tools (direct port from original)
            self._create_and_associate_tools(BASE_TOOLS, assistant.id)

            # 5. Initialize vector waves using dedicated class
            self._initialize_vector_waves(assistant.id, user.id)

            self._service_ready = True
            return assistant

        except Exception as e:
            logging_utility.critical(f"Initialization failed: {str(e)}")
            raise

    def _create_and_associate_tools(self, function_definitions: List[Dict], assistant_id: str):
        """Direct implementation of original script's tool logic"""
        for func_def in function_definitions:
            tool_name = func_def['function']['name']
            tool_function = ToolFunction(function=func_def['function'])

            # Create tool
            tool = self.client.tool_service.create_tool(
                name=tool_name,
                type='function',
                function=tool_function,
                assistant_id=assistant_id
            )

            # Explicit association (mirrors original script)
            self.client.tool_service.associate_tool_with_assistant(
                tool_id=tool.id,
                assistant_id=assistant_id
            )

            logging_utility.info(f"Created tool: {tool_name} ({tool.id})")

    def _initialize_vector_waves(self, assistant_id: str, user_id: str):
        """Proper initialization using AssistantVectorWaves"""
        vector_waves = AssistantVectorWaves(
            vector_service=self.client.vector_service,
            assistant_id=assistant_id,
            user_id=user_id
        )

        # Initialize stores (creates and attaches automatically)
        vector_waves._initialize_core_waves()
        logging_utility.info("Vector stores initialized: %s", list(vector_waves.waves.keys()))

    def is_ready(self) -> bool:
        """Check if initialization completed successfully"""
        return self._service_ready

    def get_initialization_status(self) -> dict:
        """Returns detailed initialization status for health checks"""
        status = {
            "ready": self._service_ready,
            "components": {
                "database_connected": False,
                "vector_store_healthy": False,
                "assistant_configured": False
            }
        }

        try:
            # Check database connection
            with self.SessionLocal() as session:
                session.execute(text("SELECT 1"))
                status["components"]["database_connected"] = True
        except Exception:
            pass

        # Check vector store health
        status["components"]["vector_store_healthy"] = self.client.vector_service.health_check()

        # Check if core assistant exists
        status["components"]["assistant_configured"] = hasattr(self.client.assistant_service, "default_assistant_id")

        return status
