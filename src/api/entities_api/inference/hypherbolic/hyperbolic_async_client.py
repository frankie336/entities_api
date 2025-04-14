import asyncio
import json
from typing import AsyncGenerator

import httpx


class AsyncHyperbolicClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.hyperbolic.xyz/v1",
        max_retries: int = 3,
        timeout: int = 20,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.max_retries = max_retries
        self.timeout = timeout

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        self.client = httpx.AsyncClient(
            timeout=timeout, headers=self.headers, follow_redirects=True, http2=True
        )

    async def stream_chat_completion(
        self,
        prompt: str,
        model: str = "Qwen/QwQ-32B-Preview",
        temperature: float = 0.1,
        top_p: float = 0.9,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """
        Streams tokens asynchronously from Hyperbolic chat completion API.
        Includes exponential backoff retry logic and internal error guard.
        """
        url = f"{self.base_url}/chat/completions"
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "model": model,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stream": True,
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                async with self.client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        try:
                            chunk = json.loads(line)

                            if chunk.get("object") == "error":
                                print(
                                    f"[!] Server error: {chunk.get('message', 'Unknown error')}"
                                )
                                break

                            content = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            print(f"[!] Invalid JSON: {line}")
                    return  # Exit on success
            except Exception as e:
                if attempt < self.max_retries:
                    backoff = 2 ** (attempt - 1)
                    print(f"[Retry {attempt}] Error: {e} — Backing off {backoff}s...")
                    await asyncio.sleep(backoff)
                else:
                    print(f"[!] Max retries exceeded. Final error: {e}")
                    raise

    async def aclose(self):
        await self.client.aclose()
