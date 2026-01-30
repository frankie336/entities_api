import asyncio
import os
import queue
import threading
from functools import lru_cache
from typing import AsyncGenerator, Generator, Optional, TypeVar

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from projectdavid import Entity
from together import Together

# Import your AsyncHyperbolicClient definition
from entities_api.clients.unified_async_client import AsyncUnifiedInferenceClient
from src.api.entities_api.services.logging_service import LoggingUtility

load_dotenv()
LOG = LoggingUtility()

T = TypeVar("T")


# -----------------------------------------------------------------------------
# HIGH-PERFORMANCE STREAMING BRIDGE (Module Level)
# -----------------------------------------------------------------------------
def async_to_sync_stream(agen: AsyncGenerator[T, None]) -> Generator[T, None, None]:
    """
    True Streaming Bridge: Runs the async stream in a continuous background thread.
    This prevents 'Stop-and-Go' latency during the SSL Handshake and generation.
    """
    # Use a thread-safe queue to bridge the async worker and sync consumer
    # maxsize=100 provides a healthy buffer if the consumer is slower than the network
    q = queue.Queue(maxsize=100)

    # Sentinel objects to mark stream events
    NEXT_ITEM = object()
    DONE = object()

    def _producer():
        """
        Runs in a separate thread.
        Maintains a healthy, continuous event loop for the connection.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def consume_stream():
            try:
                # The connection is established and maintained continuously here
                async for item in agen:
                    q.put((NEXT_ITEM, item))
            except Exception as e:
                # Pass exceptions (like connection errors) to the main thread
                q.put((NEXT_ITEM, e))
            finally:
                q.put((DONE, None))

        try:
            loop.run_until_complete(consume_stream())
        finally:
            loop.close()

    # 1. Start the connection in the background immediately
    t = threading.Thread(target=_producer, daemon=True)
    t.start()

    # 2. Consume items the moment they hit the queue
    while True:
        status, item = q.get()

        if status is DONE:
            break

        if isinstance(item, Exception):
            raise item

        yield item


# -----------------------------------------------------------------------------
# CLIENT FACTORY
# -----------------------------------------------------------------------------
class ClientFactoryMixin:
    """
    Factory / cache for external SDK clients.
    """

    @lru_cache(maxsize=32)
    def _get_openai_client(
        self, *, api_key: Optional[str], base_url: Optional[str] = None
    ) -> OpenAI:
        if not api_key:
            raise RuntimeError("api_key required for OpenAI client")
        try:
            return OpenAI(
                api_key=api_key,
                base_url=base_url or os.getenv("HYPERBOLIC_BASE_URL"),
                timeout=httpx.Timeout(connect=30.0, timeout=30.0, read=30.0),
            )
        except Exception as exc:
            LOG.error("OpenAI client init failed: %s", exc, exc_info=True)
            raise

    @lru_cache(maxsize=32)
    def _get_together_client(
        self, *, api_key: Optional[str], base_url: Optional[str] = None
    ) -> Together:
        if not api_key:
            raise RuntimeError("api_key required for Together client")
        try:
            return Together(api_key=api_key, base_url=base_url)
        except Exception as exc:
            LOG.error("Together client init failed: %s", exc, exc_info=True)
            raise

    @lru_cache(maxsize=32)
    def _get_project_david_client(
        self, *, api_key: Optional[str], base_url: Optional[str]
    ) -> Entity:
        if not api_key or not base_url:
            raise RuntimeError("api_key + base_url required for Entity client")
        try:
            return Entity(api_key=api_key, base_url=base_url)
        except Exception as exc:
            LOG.error("Project-David client init failed: %s", exc, exc_info=True)
            raise

    @lru_cache(maxsize=32)
    def _get_unified_client(
        self, *, api_key: Optional[str], base_url: Optional[str]
    ) -> AsyncUnifiedInferenceClient:
        """
        Returns a cached AsyncHyperbolicClient.
        NOTE: This caches the CONNECTION POOL, which improves performance.
        """
        if not api_key or not base_url:
            raise RuntimeError("api_key + base_url required for Hyperbolic client")
        try:
            return AsyncUnifiedInferenceClient(api_key=api_key, base_url=base_url)
        except Exception as exc:
            LOG.error("Hyperbolic client init failed: %s", exc, exc_info=True)
            raise
