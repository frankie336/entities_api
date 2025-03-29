# entities/clients/code_execution_client.py
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional, Generator
from dotenv import load_dotenv
from entities.clients.actions import ActionsClient
from entities.clients.assistants import AssistantsClient
from entities.clients.messages import MessagesClient
from entities.clients.runs import RunsClient
from entities.clients.threads import ThreadsClient
from entities.clients.tools import ToolSClient
from entities.clients.users import UserClient
from entities.dependencies import SessionLocal
from entities.services.logging_service import LoggingUtility
from entities.services.vector_store_service import VectorStoreService

# Load environment variables from .env file
load_dotenv()

# Initialize logging utility
logging_utility = LoggingUtility()


class EntitiesInternalInterface:
    def __init__(
            self,
            base_url: Optional[str] = None,
            api_key: Optional[str] = None,
            available_functions: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the main client with configuration.
        Optionally, a configuration object could be injected here
        to decouple from environment variables for better testability.
        """
        self.base_url = base_url or os.getenv('ASSISTANTS_BASE_URL', 'http://localhost:9000/')
        self.api_key = api_key or os.getenv('API_KEY', 'your_api_key')

        self._session_factory = SessionLocal

        logging_utility.info("CommonEntitiesInternalInterface initialized with base_url: %s", self.base_url)

        # Lazy initialization caches for service instances
        self._user_service: Optional[UserClient] = None
        self._assistant_service: Optional[AssistantsClient] = None
        self._tool_service: Optional[ToolSClient] = None
        self._thread_service: Optional[ThreadsClient] = None
        self._message_service: Optional[MessagesClient] = None
        self._run_service: Optional[RunsClient] = None
        self._action_service: Optional[ActionsClient] = None
        self._vector_service: Optional[VectorStoreService] = None

    @property
    def user_service(self) -> UserClient:
        if self._user_service is None:
            self._user_service = UserClient(base_url=self.base_url, api_key=self.api_key)
        return self._user_service

    @property
    def assistant_service(self) -> AssistantsClient:
        if self._assistant_service is None:
            self._assistant_service = AssistantsClient(base_url=self.base_url, api_key=self.api_key)
        return self._assistant_service

    @property
    def tool_service(self) -> ToolSClient:
        if self._tool_service is None:
            self._tool_service = ToolSClient()
        return self._tool_service

    @property
    def thread_service(self) -> ThreadsClient:
        if self._thread_service is None:
            self._thread_service = ThreadsClient(base_url=self.base_url, api_key=self.api_key)
        return self._thread_service

    @property
    def message_service(self) -> MessagesClient:
        if self._message_service is None:
            self._message_service = MessagesClient(base_url=self.base_url, api_key=self.api_key)
        return self._message_service

    @property
    def run_service(self) -> RunsClient:
        if self._run_service is None:
            self._run_service = RunsClient()
        return self._run_service

    @property
    def action_service(self) -> ActionsClient:
        if self._action_service is None:
            self._action_service = ActionsClient()
        return self._action_service

    # The Vector Database docker container, QDart has some
    # sort of bug or incorrect implementation
    # preventing traffic through its client
    # traversing FastAPI(). This is  special
    # Case direct call to qdrant/qdrant
    @property
    def vector_service(self) -> VectorStoreService:
        if self._vector_service is None:
            session = self._session_factory()
            self._vector_service = VectorStoreService()
        return self._vector_service

    @contextmanager
    def vector_session(self) -> Generator[VectorStoreService, None, None]:
        """Context manager for explicit session control"""
        session = self._session_factory()
        try:
            service = VectorStoreService(session)
            yield service
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


    def close(self):
        """Clean up resources explicitly"""
        if self._vector_service:
            self._vector_service.db.close()