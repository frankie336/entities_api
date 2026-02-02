import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

# ------------------------------------------------------------------
# GLOBAL CLIENT CACHE (Critical for Performance)
# ------------------------------------------------------------------
# Stores instances as: { "api_key_hash": AsyncUnifiedInferenceClient_Instance }
_ACTIVE_CLIENTS: Dict[str, "AsyncUnifiedInferenceClient"] = {}


class AsyncUnifiedInferenceClient:
    """
    A generic, asynchronous client for OpenAI-compatible inference providers.
    Designed for long-lived connection pooling.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int = 180,
        enable_chunk_logging: bool = False,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.enable_chunk_logging = enable_chunk_logging

        # ---------------------------------------------------------
        # FILE-LEVEL LOGGING SETUP (DEBUGGING)
        # ---------------------------------------------------------
        if self.enable_chunk_logging:
            log_file = os.path.abspath("unified_inference_debug.log")
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(levelname)s - %(message)s",
                handlers=[
                    logging.FileHandler(log_file, mode="a", encoding="utf-8"),
                    logging.StreamHandler(),
                ],
                force=True,
            )
            self.file_logger = logging.getLogger("UnifiedLocalLogger")
            self.file_logger.setLevel(logging.INFO)
        else:
            self.file_logger = None

        # ---------------------------------------------------------
        # HTTPX CLIENT (The Connection Pool)
        # ---------------------------------------------------------
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            # LIMITS: Allow high concurrency
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            # HTTP/2: Disabled to prevent buffering issues with some LLM providers
            http2=False,
        )

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.1,
        **kwargs,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        url = f"{self.base_url}/chat/completions"

        payload = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "stream": True,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools
            if "tool_choice" not in payload:
                payload["tool_choice"] = "auto"

        if self.enable_chunk_logging:
            self.file_logger.info(f"START STREAM: {model} -> {url}")

        chunk_count = 0

        try:
            # Context manager ensures request cleanup, but keeps connection open in pool
            async with self.client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    error_content = await response.aread()
                    err_msg = f"Error {response.status_code}: {error_content.decode()}"
                    if self.enable_chunk_logging:
                        self.file_logger.error(f"HTTP ERROR: {err_msg}")
                    raise httpx.HTTPStatusError(
                        err_msg, request=response.request, response=response
                    )

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    # Optimization: Strip efficiently
                    line = line.strip()

                    if line == "data: [DONE]":
                        break

                    if line.startswith("data: "):
                        clean_line = line[6:]
                        try:
                            chunk_data = json.loads(clean_line)
                            chunk_count += 1

                            if self.enable_chunk_logging:
                                # Logging logic...
                                pass

                            yield chunk_data

                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            if self.enable_chunk_logging:
                self.file_logger.error(f"STREAM EXCEPTION: {e}")
            raise e

    async def aclose(self):
        """Manually close the underlying client."""
        await self.client.aclose()


# ------------------------------------------------------------------
# FACTORY FUNCTION (Use this in your Worker!)
# ------------------------------------------------------------------
def get_cached_client(
    api_key: str,
    base_url: str,
    enable_logging: bool = False
) -> AsyncUnifiedInferenceClient:
    """
    Returns a cached client instance for the given API key/Base URL combo.
    This prevents SSL Handshake overhead on every request.
    """
    cache_key = f"{api_key[-6:]}@{base_url}"  # Simple hash key

    if cache_key not in _ACTIVE_CLIENTS:
        client = AsyncUnifiedInferenceClient(
            api_key=api_key,
            base_url=base_url,
            enable_chunk_logging=enable_logging
        )
        _ACTIVE_CLIENTS[cache_key] = client

    # Check if the event loop is closed (rare edge case in some runners)
    client = _ACTIVE_CLIENTS[cache_key]
    if client.client.is_closed:
        # Re-create if closed
        client = AsyncUnifiedInferenceClient(
            api_key=api_key,
            base_url=base_url,
            enable_chunk_logging=enable_logging
        )
        _ACTIVE_CLIENTS[cache_key] = client

    return client
