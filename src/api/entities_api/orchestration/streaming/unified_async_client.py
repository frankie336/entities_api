import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx


class AsyncUnifiedInferenceClient:
    """
    A generic, asynchronous client for OpenAI-compatible inference providers
    (Hyperbolic, TogetherAI, DeepSeek, vLLM, etc.).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int = 180,
        enable_chunk_logging: bool = False,
    ):
        """
        :param api_key: Provider API Key
        :param base_url: The full base URL (e.g. 'https://api.hyperbolic.xyz/v1' or 'https://api.together.xyz/v1')
        :param timeout: Request timeout in seconds
        :param enable_chunk_logging: If True, writes raw stream chunks to a local log file for debugging.
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.enable_chunk_logging = enable_chunk_logging

        # ---------------------------------------------------------
        # FILE-LEVEL LOGGING SETUP (DEBUGGING)
        # ---------------------------------------------------------
        if self.enable_chunk_logging:
            # Generic log file name
            log_file = os.path.abspath("unified_inference_debug.log")

            # Configure logging
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(levelname)s - %(message)s",
                handlers=[
                    logging.FileHandler(log_file, mode="a", encoding="utf-8"),
                    logging.StreamHandler(),  # Also print to console
                ],
                force=True,  # Override any existing config
            )

            self.file_logger = logging.getLogger("UnifiedLocalLogger")
            self.file_logger.setLevel(logging.INFO)

            # Test write
            self.file_logger.info(f"=== LOGGER INITIALIZED at {log_file} ===")
            print(f"✓ Debug log file created: {log_file}")
        else:
            self.file_logger = None

        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            # HTTP/2 is disabled to prevent streaming buffering issues common with some providers
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
            self.file_logger.info("=== STARTING NEW STREAM REQUEST ===")
            self.file_logger.info(f"Target URL: {url}")
            self.file_logger.info(f"Model: {model}")
            self.file_logger.info(f"Messages count: {len(messages)}")

        chunk_count = 0

        try:
            async with self.client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    error_content = await response.aread()
                    err_msg = f"Error {response.status_code}: {error_content.decode()}"

                    if self.enable_chunk_logging:
                        self.file_logger.error(f"HTTP ERROR: {err_msg}")

                    raise httpx.HTTPStatusError(
                        err_msg,
                        request=response.request,
                        response=response,
                    )

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    line = line.strip()

                    if self.enable_chunk_logging:
                        self.file_logger.info(f"RAW LINE: {line}")

                    # Standard OpenAI End-of-Stream signal
                    if line == "data: [DONE]":
                        if self.enable_chunk_logging:
                            self.file_logger.info("=== STREAM COMPLETED ===")
                        break

                    # Standard SSE data prefix
                    if line.startswith("data: "):
                        clean_line = line[6:]
                        try:
                            chunk_data = json.loads(clean_line)
                            chunk_count += 1

                            if self.enable_chunk_logging:
                                self.file_logger.info(f"--- CHUNK #{chunk_count} ---")
                                self.file_logger.info(json.dumps(chunk_data, indent=2))

                                # Log specific content for easier reading
                                if "choices" in chunk_data and chunk_data["choices"]:
                                    delta = chunk_data["choices"][0].get("delta", {})
                                    if "content" in delta:
                                        self.file_logger.info(
                                            f"CONTENT: {delta['content']}"
                                        )
                                    if "tool_calls" in delta:
                                        self.file_logger.info(
                                            f"TOOL_CALL: {delta['tool_calls']}"
                                        )

                            yield chunk_data

                        except json.JSONDecodeError as je:
                            if self.enable_chunk_logging:
                                self.file_logger.error(f"JSON DECODE ERROR: {je}")
                                self.file_logger.error(f"Bad JSON: {clean_line}")
                            continue

                if self.enable_chunk_logging:
                    self.file_logger.info(f"=== TOTAL CHUNKS: {chunk_count} ===")

        except Exception as e:
            if self.enable_chunk_logging:
                self.file_logger.error(f"STREAM EXCEPTION: {type(e).__name__}: {e}")
            raise e

    async def aclose(self):
        await self.client.aclose()
