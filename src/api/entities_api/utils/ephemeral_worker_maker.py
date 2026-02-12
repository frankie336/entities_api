import asyncio
import os
import uuid
from typing import Optional

from dotenv import load_dotenv
from projectdavid import Entity

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
            name=name,
            model=model,
            tools=SUPERVISOR_TOOLS,
        )

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


# ------------------------------------------------------------------
# Usage Example
# ------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Initialize the manager
    manager = AssistantManager()

    # 2. Create the primary assistant (Sync)
    try:
        main_assistant = manager.create_primary_assistant()
        print(f"Created Main Assistant: {main_assistant}")
    except Exception as e:
        print(f"Error creating main assistant: {e}")

    # 3. Create an ephemeral worker (Async)
    async def main():
        print("Creating ephemeral worker...")
        worker = await manager.create_ephemeral_supervisor()
        print(f"Created Worker: {worker}")

    asyncio.run(main())
