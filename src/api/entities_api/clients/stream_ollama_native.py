# src/api/entities_api/clients/stream_ollama_native.py
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncGenerator, Dict, List

import httpx
from projectdavid_common.utilities.logging_service import LoggingUtility

LOG = LoggingUtility()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").removesuffix(
    "/v1"
)


async def stream_ollama_raw(
    messages: List[Dict[str, str]],
    model: str = "qwen3:4b",
    *,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.6,
    max_tokens: int = 10_000,
    think: bool = False,
    tools: List[Dict] | None = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    url = f"{base_url}/api/chat"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": think,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    if tools:
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise RuntimeError(
                    f"Ollama returned HTTP {response.status_code}: {body.decode()}"
                )

            async for raw_line in response.aiter_lines():
                raw_line = raw_line.strip()
                if not raw_line:
                    continue

                try:
                    chunk = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    LOG.warning(
                        "Ollama: malformed JSON line skipped (%s): %r", exc, raw_line
                    )
                    continue

                yield chunk
                if chunk.get("done"):
                    return


class OllamaNativeStreamMixin:
    OLLAMA_BASE_URL: str = OLLAMA_BASE_URL

    async def _stream_ollama_raw(
        self,
        messages: List[Dict],
        model: str,
        *,
        temperature: float = 0.6,
        max_tokens: int = 10_000,
        think: bool = False,
        tools: List[Dict] | None = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        async for chunk in stream_ollama_raw(
            messages=messages,
            model=model,
            base_url=getattr(self, "OLLAMA_BASE_URL", OLLAMA_BASE_URL),
            temperature=temperature,
            max_tokens=max_tokens,
            think=False,
            tools=tools,
        ):
            yield chunk


async def _smoke_test_xml_tool_call() -> None:
    from entities_api.clients.delta_normalizer import DeltaNormalizer

    print("\n══════════════════════════════════════════")
    print("  SMOKE TEST — <fc> XML TOOL CALL CYCLE")
    print("══════════════════════════════════════════")

    tools_schema = [
        {
            "name": "get_current_weather",
            "description": "Get the current weather for a given city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "The city name, e.g. London",
                    }
                },
                "required": ["city"],
            },
        }
    ]

    sys_prompt = f"""You are a helpful AI assistant. You have access to the following tools:
{json.dumps(tools_schema, indent=2)}

CRITICAL INSTRUCTIONS:
1. If you need to use a tool, you MUST wrap the JSON invocation strictly inside <fc> and </fc> tags.
2. DO NOT discuss or mention the <fc> tags in your conversational text. Only use them when calling the tool.
3. The content inside the tags MUST be valid JSON.
4. DO NOT use <think> tags or output internal reasoning. Provide direct answers or tool calls only.

Example:
<fc>{{"name": "get_current_weather", "arguments": {{"city": "London"}}}}</fc>
"""

    messages: List[Dict] = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "What is the weather like in Paris right now?"},
    ]

    print(
        "\n[TURN 1] Sending prompt instructing <fc> format (Native Tools Disabled, think=False) …\n"
    )

    tool_call_received: Dict | None = None

    async for chunk in DeltaNormalizer.async_iter_deltas(
        stream_ollama_raw(
            messages, model="qwen3:4b", think=False, tools=None, temperature=0.0
        ),
        "smoke-xml-fc-t1",
    ):
        ctype = chunk.get("type")

        if ctype == "reasoning":
            print(f"[THINK] {chunk['content']}", end="", flush=True)

        elif ctype == "content":
            print(chunk["content"], end="", flush=True)

        elif ctype == "tool_call":
            tool_call_received = chunk["content"]
            fn_name = tool_call_received.get("name", "?")
            fn_args = tool_call_received.get("arguments", "{}")
            print(f"\n\n[FINAL ASSEMBLED XML TOOL CALL DETECTED]")
            print(f"  name      : {fn_name}")
            print(f"  arguments : {fn_args}")

        elif ctype == "error":
            print(f"\n[ERROR] {chunk['content']}")
            return

    if not tool_call_received:
        print("\n⚠️  Model did NOT emit an <fc> tool call. Check prompt alignment.")
        return

    # ── Simulate tool execution ───────────────────────────────────────────
    fn_name = tool_call_received["name"]
    fn_args_raw = tool_call_received.get("arguments", "{}")
    fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
    city = fn_args.get("city", "Paris")

    fake_result = json.dumps(
        {"city": city, "temperature": "18°C", "condition": "Partly cloudy"}
    )
    print(f"\n[TOOL RESULT] Injecting fake result: {fake_result}\n")

    # ── Turn 2: send tool result back and get final answer ────────────────
    messages += [
        {
            "role": "assistant",
            "content": f"<fc>{json.dumps(tool_call_received)}</fc>",
        },
        # CHANGED TO PROPER TOOL ROLE
        {"role": "tool", "content": fake_result},
    ]

    print("[TURN 2] Sending tool result, awaiting final answer …\n")

    async for chunk in DeltaNormalizer.async_iter_deltas(
        stream_ollama_raw(
            messages, model="qwen3:4b", think=False, tools=None, temperature=0.0
        ),
        "smoke-xml-fc-t2",
    ):
        ctype = chunk.get("type")
        if ctype == "content":
            print(chunk["content"], end="", flush=True)

    print("\n\n[DONE]\n")


if __name__ == "__main__":
    asyncio.run(_smoke_test_xml_tool_call())
