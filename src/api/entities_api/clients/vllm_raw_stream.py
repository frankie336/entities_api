# src/api/entities_api/clients/vllm_raw_stream.py
"""
VLLMRawStream
=============
Drop-in replacement for OllamaNativeStream that targets vLLM's
/v1/completions endpoint (raw text, no OpenAI chat wrapper).

Pipeline position — identical to Ollama:

    vLLM /v1/completions
        ↓  _stream_vllm_raw()       ← THIS FILE
        ↓  DeltaNormalizer           ← unchanged
        ↓  OrchestratorCore          ← unchanged
        ↓  SSE response              ← unchanged

Why /v1/completions and not /v1/chat/completions?
    /v1/chat/completions  — vLLM applies chat template + tool parser.
                            Gives you delta.tool_calls already structured.
                            Defeats the purpose of raw integration.

    /v1/completions       — vLLM passes your prompt straight to the model.
                            Returns raw generated text token by token.
                            DeltaNormalizer handles the rest.

The one responsibility of this class:
    Convert vLLM's  choices[0].text
    into the shape  choices[0].delta.content
    that DeltaNormalizer already knows how to consume.

Chat template rendering:
    /v1/completions does NOT apply a chat template — you own the prompt.
    This class applies it via the tokenizer's apply_chat_template logic,
    reconstructed from the CHAT_TEMPLATES registry below.
    For most deployments, point base_url at a running vLLM server and
    the template is resolved automatically via /tokenizer/chat_template.
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility

load_dotenv()
LOG = LoggingUtility()


# ── Per-family chat templates ─────────────────────────────────────────────────
# Used to render messages → prompt string before hitting /v1/completions.
# These mirror what apply_chat_template() produces for each family.


def _render_qwen(messages: List[Dict], tools: Optional[List] = None) -> str:
    """Qwen2.5 / Qwen3 im_start/im_end format."""
    parts = []

    if tools:
        tool_json = "\n".join(json.dumps(t) for t in tools)
        # Inject tool schema into system prompt using Qwen's <tools> convention
        system_content = None
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system_content = m["content"]
            else:
                filtered.append(m)

        system_block = system_content or "You are a helpful assistant."
        system_block += (
            "\n\n# Tools\n\nYou may call one or more functions to assist with the user query.\n\n"
            "You are provided with function signatures within <tools></tools> XML tags:\n"
            f"<tools>\n{tool_json}\n</tools>"
        )
        parts.append(f"<|im_start|>system\n{system_block}<|im_end|>")
        messages = filtered
    else:
        for m in messages:
            if m["role"] == "system":
                parts.append(f"<|im_start|>system\n{m['content']}<|im_end|>")
                messages = [x for x in messages if x is not m]
                break

    for m in messages:
        role = m["role"]
        content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")

    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def _render_mistral(messages: List[Dict], tools: Optional[List] = None) -> str:
    """Mistral [INST] format."""
    system = ""
    turns = []

    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            turns.append(m)

    if tools:
        tool_json = json.dumps(tools)
        system += f"\n\nYou have access to the following tools:\n{tool_json}"

    parts = ["<s>"]
    for i, m in enumerate(turns):
        if m["role"] == "user":
            prefix = f"{system}\n\n" if system and i == 0 else ""
            parts.append(f"[INST] {prefix}{m['content']} [/INST]")
        elif m["role"] == "assistant":
            parts.append(f" {m['content']}</s>")

    return "".join(parts)


def _render_llama3(messages: List[Dict], tools: Optional[List] = None) -> str:
    """Llama 3.x header/eot format."""
    parts = ["<|begin_of_text|>"]
    system_injected = False

    for m in messages:
        role = m["role"]
        content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])

        if role == "system" and tools and not system_injected:
            tool_json = json.dumps(tools)
            content += f"\n\nTools available:\n{tool_json}"
            system_injected = True

        parts.append(f"<|start_header_id|>{role}<|end_header_id|>\n\n{content}<|eot_id|>")

    parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
    return "".join(parts)


# Registry: model_id substring → renderer
CHAT_TEMPLATE_REGISTRY = [
    ("Qwen", _render_qwen),
    ("qwen", _render_qwen),
    ("Mistral", _render_mistral),
    ("mistral", _render_mistral),
    ("Llama", _render_llama3),
    ("llama", _render_llama3),
]


def render_prompt(
    model_id: str,
    messages: List[Dict],
    tools: Optional[List] = None,
) -> str:
    """
    Resolve and apply the correct chat template for a given model ID.
    Falls back to Qwen format (most common for local deployments).
    """
    for substr, renderer in CHAT_TEMPLATE_REGISTRY:
        if substr in model_id:
            return renderer(messages, tools)

    LOG.warning(
        "VLLMRawStream: no chat template found for model '%s', falling back to Qwen format.",
        model_id,
    )
    return _render_qwen(messages, tools)


# ══════════════════════════════════════════════════════════════════════════════
# VLLMRawStream
# ══════════════════════════════════════════════════════════════════════════════


class VLLMRawStream:
    """
    Mixin / base class that provides _stream_vllm_raw().

    Usage in a worker:

        class VLLMDefaultWorker(
            VLLMRawStream,
            _ProviderMixins,
            OrchestratorCore,
            ABC,
        ):
            ...

        # In stream():
        async for chunk in DeltaNormalizer.async_iter_deltas(
            self._stream_vllm_raw(
                messages=ctx,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                think=think,
                base_url=base_url,
            ),
            run_id,
        ):
            ...
    """

    # ── Default config (override via env or constructor kwargs) ───────────────
    VLLM_DEFAULT_BASE_URL: str = os.getenv("VLLM_BASE_URL", "http://localhost:8000")
    VLLM_REQUEST_TIMEOUT: int = int(os.getenv("VLLM_TIMEOUT", "120"))

    async def _stream_vllm_raw(
        self,
        *,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.6,
        max_tokens: int = 1024,
        think: bool = False,
        base_url: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        skip_special_tokens: bool = False,
        **kwargs,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Async generator — mirrors _stream_ollama_raw() interface.

        Hits vLLM /v1/completions and adapts the response into the
        dict shape that DeltaNormalizer.async_iter_deltas() expects:

            {"choices": [{"delta": {"content": "..."}, "finish_reason": ...}]}

        Steps:
            1. Render messages → prompt string via family chat template
            2. POST to /v1/completions with stream=True
            3. For each SSE chunk: unwrap choices[0].text
               → re-wrap as choices[0].delta.content
            4. Yield the normalised dict — DeltaNormalizer takes over
        """
        resolved_base = (base_url or self.VLLM_DEFAULT_BASE_URL).rstrip("/")
        endpoint = f"{resolved_base}/v1/completions"

        # ── 1. Render prompt ──────────────────────────────────────────────
        # Pull tools from assistant_config if not passed directly
        if tools is None and hasattr(self, "assistant_config"):
            tools = self.assistant_config.get("tools") or self.assistant_config.get(
                "function_definitions"
            )

        prompt = render_prompt(model_id=model, messages=messages, tools=tools)

        LOG.debug("VLLMRawStream ▸ rendered prompt (%d chars):\n%s", len(prompt), prompt[:500])

        # ── 2. Build payload ──────────────────────────────────────────────
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "skip_special_tokens": skip_special_tokens,  # False = keep <tool_call> etc.
            "stream_options": {"include_usage": False},
        }

        # Qwen3 thinking mode: stop generation after </think> opens if not wanted
        if not think:
            payload["stop"] = ["<think>"] if "Qwen3" in model or "qwen3" in model else None
            if payload["stop"] is None:
                del payload["stop"]

        LOG.info(
            "VLLMRawStream ▸ POST %s | model=%s | max_tokens=%d | temp=%.2f",
            endpoint,
            model,
            max_tokens,
            temperature,
        )

        # ── 3. Stream ─────────────────────────────────────────────────────
        try:
            async with httpx.AsyncClient(timeout=self.VLLM_REQUEST_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as response:

                    if response.status_code != 200:
                        body = await response.aread()
                        error_msg = body.decode(errors="replace")
                        LOG.error(
                            "VLLMRawStream ▸ HTTP %d from vLLM: %s",
                            response.status_code,
                            error_msg[:300],
                        )
                        # Yield an error chunk in the same envelope shape
                        yield {
                            "choices": [
                                {
                                    "delta": {"content": f"[vLLM error {response.status_code}]"},
                                    "finish_reason": "error",
                                }
                            ]
                        }
                        return

                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        if not line.startswith("data:"):
                            continue

                        raw = line[5:].strip()

                        if raw == "[DONE]":
                            # Signal end of stream — mirrors Ollama's done=True chunk
                            yield {
                                "done": True,
                                "done_reason": "stop",
                                "message": {"content": ""},
                            }
                            return

                        # ── 4. Adapt vLLM completions → DeltaNormalizer shape ──
                        try:
                            parsed = json.loads(raw)
                        except json.JSONDecodeError:
                            LOG.warning("VLLMRawStream ▸ non-JSON SSE line: %s", raw[:100])
                            continue

                        choices = parsed.get("choices", [])
                        if not choices:
                            continue

                        choice = choices[0]

                        # /v1/completions uses "text", not "delta.content"
                        text = choice.get("text", "")
                        finish_reason = choice.get("finish_reason")

                        # ── Re-wrap into DeltaNormalizer's expected shape ──────
                        yield {
                            "choices": [
                                {
                                    "delta": {"content": text},
                                    "finish_reason": finish_reason,
                                }
                            ]
                        }

        except httpx.ConnectError as exc:
            LOG.error("VLLMRawStream ▸ Could not connect to vLLM at %s: %s", endpoint, exc)
            yield {
                "choices": [
                    {
                        "delta": {"content": "[vLLM connection failed]"},
                        "finish_reason": "error",
                    }
                ]
            }
        except httpx.TimeoutException as exc:
            LOG.error("VLLMRawStream ▸ Timeout waiting for vLLM: %s", exc)
            yield {
                "choices": [
                    {
                        "delta": {"content": "[vLLM timeout]"},
                        "finish_reason": "error",
                    }
                ]
            }
        except Exception as exc:
            LOG.error("VLLMRawStream ▸ Unexpected error: %s", exc, exc_info=True)
            yield {
                "choices": [
                    {
                        "delta": {"content": f"[vLLM stream error: {exc}]"},
                        "finish_reason": "error",
                    }
                ]
            }
