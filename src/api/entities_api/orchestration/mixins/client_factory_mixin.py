"""
Factory / cache for external SDK clients (OpenAI, Together, ProjectDavid).
No project-internal state beyond `self._openai_client`, etc.
"""

import os
from functools import lru_cache
from typing import Optional

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from projectdavid import Entity
from together import Together

from src.api.entities_api.services.logging_service import LoggingUtility

from src.api.entities_api.orchestration.streaming.hyperbolic_async_client import (
    AsyncHyperbolicClient,
)
from src.api.entities_api.utils.async_to_sync import async_to_sync_stream

load_dotenv()
LOG = LoggingUtility()


class ClientFactoryMixin:

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
    def _get_hyperbolic_client(
        self, *, api_key: Optional[str], base_url: Optional[str]
    ) -> Entity:
        if not api_key or not base_url:
            raise RuntimeError("api_key + base_url required for Hyperbolic client")
        try:
            return AsyncHyperbolicClient(api_key=api_key, base_url=base_url)

        except Exception as exc:
            LOG.error("Hyperbolic client init failed: %s", exc, exc_info=True)
            raise
