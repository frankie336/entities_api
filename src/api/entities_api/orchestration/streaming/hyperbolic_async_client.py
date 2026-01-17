import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx


class AsyncHyperbolicClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.hyperbolic.xyz/v1",
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}, http2=True
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

        # 1. Build the base payload
        payload = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "stream": True,
            **kwargs,
        }

        # 2. FIX: Properly assign tools only if they exist
        if tools:
            payload["tools"] = tools
            # If tools are present and tool_choice isn't specified,
            # you might want to default to "auto", though most APIs do this.
            if "tool_choice" not in payload:
                payload["tool_choice"] = "auto"

        async with self.client.stream("POST", url, json=payload) as response:
            # It's better to catch the error here to see why the API rejected the call
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

                line = line.strip()

                if line == "data: [DONE]":
                    break

                if line.startswith("data: "):
                    clean_line = line[6:]
                    try:
                        # Yield the full dictionary so the Normalizer can see tool_calls
                        yield json.loads(clean_line)
                    except json.JSONDecodeError:
                        continue

    async def aclose(self):
        await self.client.aclose()
