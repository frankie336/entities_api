import asyncio
import os
import uuid
from typing import Any, Optional

from dotenv import load_dotenv
from projectdavid import Entity

from entities_api.constants.worker import WORKER_TOOLS
from src.api.entities_api.constants.delegator import SUPERVISOR_TOOLS

load_dotenv()


class AssistantManager:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize the AssistantManager with projectdavid Entity client.
        Uses environment variables if arguments are not provided.
        """
        self.base_url = base_url or os.getenv("BASE_URL", "http://localhost:9000")
        self.api_key = api_key or os.getenv("ADMIN_API_KEY")

        if not self.api_key:
            raise ValueError("ADMIN_API_KEY is not set in environment or arguments.")

        self.client = Entity(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    def create_primary_assistant(
        self, name: str = "Test Assistant", model: str = "gpt-oss-120b"
    ):
        """
        Creates the main supervisor assistant (Synchronous).
        """

        return self.client.assistants.create_assistant(
            name=name, model=model, tools=SUPERVISOR_TOOLS, web_access=False
        )

    def create_thread(self, name: str = "Test Assistant", model: str = "gpt-oss-120b"):
        """
        Creates the main supervisor assistant (Synchronous).
        """
        return self.client.threads.create_thread()

    async def create_ephemeral_supervisor(self):
        """
        Creates a temporary worker assistant with a unique UUID.
        Wraps the blocking SDK call in a thread for async compatibility.
        """
        ephemeral_worker = await asyncio.to_thread(
            self.client.assistants.create_assistant,
            name=f"worker_{uuid.uuid4().hex[:8]}",
            description="Temp research supervisor",
            tools=SUPERVISOR_TOOLS,
            deep_research=False,
        )
        return ephemeral_worker

    async def create_ephemeral_worker_assistant(self):
        """
        Creates the sub-worker.
        Crucially, we inject 'research_worker_calling': True into meta_data.
        This allows QwenBaseWorker to identify its role upon loading.
        """
        ephemeral_worker = await asyncio.to_thread(
            self.client.assistants.create_assistant,
            name=f"worker_{uuid.uuid4().hex[:8]}",
            description="Temp assistant for deep research",
            tools=WORKER_TOOLS,
            deep_research=False,
            # ✅ FIX: Pass state here so the worker knows what it is immediately
            meta_data={"research_worker_calling": True},
        )

        return ephemeral_worker

    async def delete_assistant(self, assistant_id: str, permanent: bool = False) -> Any:
        """
        Deletes a temporary worker assistant.
        """
        return await asyncio.to_thread(
            self.client.assistants.delete_assistant,
            assistant_id=assistant_id,
            permanent=permanent,
        )
