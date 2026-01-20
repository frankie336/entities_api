import json
import httpx
from typing import Any, AsyncGenerator, Dict, List, Optional
from projectdavid_common.utilities.logging_service import LoggingUtility

LOG = LoggingUtility()


class AsyncHyperbolicClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.hyperbolic.xyz/v1",
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

        # ---------------------------------------------------------
        # FIX 1: Disable HTTP/2.
        # 'requests' uses HTTP/1.1. Streaming over HTTP/2 is often
        # flaky on specific inference providers/proxies.
        # ---------------------------------------------------------
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"  # FIX 2: Explicit Content-Type
            },
            http2=False  # <--- CHANGED FROM TRUE
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

        # FIX 3: Ensure tools are attached correctly
        if tools:
            payload["tools"] = tools
            if "tool_choice" not in payload:
                payload["tool_choice"] = "auto"

        # DEBUG: Print the payload size/structure before sending to confirm 2nd turn behavior
        # LOG.debug(f"[HyperbolicClient] Sending request to {url}. Msgs: {len(messages)}, Tools: {len(tools or [])}")

        async with self.client.stream("POST", url, json=payload) as response:
            if response.status_code != 200:
                error_content = await response.aread()
                raise httpx.HTTPStatusError(
                    f"Error {response.status_code}: {error_content.decode()}",
                    request=response.request,
                    response=response,
                )

            async for line in response.aiter_lines():
                if not line:
                    continue

                # httpx aiter_lines gives strings, but stripping is safe
                line = line.strip()

                if line == "data: [DONE]":
                    break

                if line.startswith("data: "):
                    clean_line = line[6:]
                    try:
                        yield json.loads(clean_line)
                    except json.JSONDecodeError:
                        continue

    async def aclose(self):
        await self.client.aclose()
