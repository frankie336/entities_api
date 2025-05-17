# mixins/client_factory.py
from functools import lru_cache
from typing import Optional

import httpx
from openai import OpenAI
from projectdavid import Entity
from projectdavid_common.utilities.logging_service import LoggingUtility
from together import Together

logging_utility = LoggingUtility()


class ClientFactoryMixin:
    """Build-or-reuse external SDK clients with LRU caching."""
    _openai_client = None
    _together_client = None
    _project_david_client = None
    # ↳ move _get_openai_client(), _get_together_client(), _get_project_david_client() here

    @lru_cache(maxsize=32)
    def _get_openai_client(
        self, api_key: Optional[str], base_url: Optional[str] = None
    ) -> OpenAI:
        """
        Retrieves or creates an OpenAI client for the given API key.
        Uses an LRU cache for reuse. If api_key is None, returns the default client.
        """
        if api_key:
            logging_utility.debug("Creating client for specific key (not cached).")
            try:
                return OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=httpx.Timeout(30.0, read=30.0),
                )
            except Exception as e:
                logging_utility.error(
                    "Failed to create specific OpenAI client: %s", e, exc_info=True
                )
                if self.openai_client:
                    logging_utility.warning(
                        "Falling back to default client due to error."
                    )
                    return self.openai_client
                else:
                    raise RuntimeError(
                        "Default OpenAI client is not initialized, and specific client creation failed."
                    )
        else:
            if self.openai_client:
                logging_utility.debug(
                    "Using default OpenAI client (no specific key provided)."
                )
                return self.openai_client
            else:
                raise RuntimeError("Default OpenAI client is not initialized.")

    @lru_cache(maxsize=32)
    def _get_together_client(
        self, api_key: Optional[str], base_url: Optional[str] = None
    ) -> Together:
        """
        Retrieves or creates a Project David client for the given API key.
        Uses an LRU cache for reuse. If api_key is None, returns the default client.
        """
        if api_key:
            logging_utility.debug("Creating client for specific key (not cached).")
            try:
                return Together(
                    api_key=api_key,
                    # base_url=base_url,
                )
            except Exception as e:
                logging_utility.error(
                    "Failed to create specific TogetherAI client: %s",
                    e,
                    exc_info=True,
                )
                if self.together_client:
                    logging_utility.warning(
                        "Falling back to default client due to error."
                    )
                    return self.together_client
                else:
                    raise RuntimeError(
                        "Default TogetherAI client is not initialized, and specific client creation failed."
                    )
        else:
            if self.together_client:
                logging_utility.debug(
                    "Using default project_david client (no specific key provided)."
                )
                return self.together_client
            else:
                raise RuntimeError("Default TogetherAI client is not initialized.")

    @lru_cache(maxsize=32)
    def _get_project_david_client(
        self, api_key: Optional[str], base_url: Optional[str] = None
    ) -> Entity:
        """
        Retrieves or creates a Project David client for the given API key.
        Uses an LRU cache for reuse. If api_key is None, returns the default client.
        """
        if api_key:
            logging_utility.debug("Creating client for specific key (not cached).")
            try:
                return Entity(
                    api_key=api_key,
                    base_url=base_url,
                )
            except Exception as e:
                logging_utility.error(
                    "Failed to create specific project_david client: %s",
                    e,
                    exc_info=True,
                )
                if self.project_david_client:
                    logging_utility.warning(
                        "Falling back to default client due to error."
                    )
                    return self.project_david_client
                else:
                    raise RuntimeError(
                        "Default project_david client is not initialized, and specific client creation failed."
                    )
        else:
            if self.project_david_client:
                logging_utility.debug(
                    "Using default project_david client (no specific key provided)."
                )
                return self.project_david_client
            else:
                raise RuntimeError("Default project_david client is not initialized.")




