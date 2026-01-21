import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx


class AsyncHyperbolicClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.hyperbolic.xyz/v1",
        timeout: int = 180,
        enable_chunk_logging: bool = False,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.enable_chunk_logging = enable_chunk_logging

        # ---------------------------------------------------------
        # FILE-LEVEL LOGGING SETUP
        # ---------------------------------------------------------
        if self.enable_chunk_logging:
            log_file = os.path.abspath("hyperbolic_stream.log")

            # Configure logging with basicConfig to ensure it works
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(levelname)s - %(message)s",
                handlers=[
                    logging.FileHandler(log_file, mode="a", encoding="utf-8"),
                    logging.StreamHandler(),  # Also print to console for debugging
                ],
                force=True,  # Override any existing config
            )

            self.file_logger = logging.getLogger("HyperbolicLocalLogger")
            self.file_logger.setLevel(logging.INFO)

            # Test write
            self.file_logger.info(f"=== LOGGER INITIALIZED at {log_file} ===")
            print(f"✓ Log file created: {log_file}")
        else:
            self.file_logger = None

        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
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

                    if line == "data: [DONE]":
                        if self.enable_chunk_logging:
                            self.file_logger.info("=== STREAM COMPLETED ===")
                        break

                    if line.startswith("data: "):
                        clean_line = line[6:]
                        try:
                            chunk_data = json.loads(clean_line)
                            chunk_count += 1

                            if self.enable_chunk_logging:
                                self.file_logger.info(f"--- CHUNK #{chunk_count} ---")
                                self.file_logger.info(json.dumps(chunk_data, indent=2))

                                # Log specific content if available
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
