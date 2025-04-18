# entities_api/inference/deepseek/deepseek_chat_inference.py
"""
DeepSeekChatInference
---------------------
• Async streaming via **AsyncDeepSeekClient** (direct DeepSeek API)
• Works with *any* DeepSeek model you pass at runtime
• Re‑uses BaseInference utilities for reasoning, code‑interpreter,
  function‑calls, cancellation, etc.
"""

from __future__ import annotations

import json
import os
from abc import ABC
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from projectdavid_common import ValidationInterface
from projectdavid_common.utilities.logging_service import LoggingUtility

from entities_api.inference.base_inference import BaseInference
from entities_api.inference.deepseek.deepseek_async_client import \
    AsyncDeepSeekClient
from entities_api.utils.async_to_sync import async_to_sync_stream

load_dotenv()
log = LoggingUtility()


class DeepSeekChatInference(BaseInference, ABC):
    """
    Generic DeepSeek inference class – handles every DeepSeek model
    (“deepseek-chat”, “deepseek-reasoner”, DeepSeek‑R1/V3, …).
    """

    # ------------------------------------------------------------------ #
    # Provider‑specific boot‑strap (optional)
    # ------------------------------------------------------------------ #
    def setup_services(self) -> None:  # noqa: D401
        log.debug("DeepSeekChatInference services initialised (noop).")

    # ------------------------------------------------------------------ #
    # 1)  Main streaming generator
    # ------------------------------------------------------------------ #
    def stream(
        self,
        thread_id: str,
        message_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        stream_reasoning: bool = True,
        api_key: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Yields JSON event chunks identical to the other *Inference classes.
        """

        # ---------- cancellation listener ----------------------------- #
        self.start_cancellation_listener(run_id)

        # ---------- canonical model map (if user sent vendor prefix) --- #
        if self._get_model_map(value=model):
            model = self._get_model_map(value=model)

        # ---------- fetch context window ------------------------------ #
        messages = self._set_up_context_window(assistant_id, thread_id, trunk=True)

        # ---------- client init --------------------------------------- #
        if not api_key:
            err = f"Run {run_id}: DeepSeek API key missing."
            log.error(err)
            yield json.dumps({"type": "error", "content": err})
            return

        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        client = AsyncDeepSeekClient(api_key=api_key, base_url=base_url)

        assistant_reply: str = ""
        accumulated: str = ""
        reasoning: str = ""
        in_reasoning, code_mode = False, False
        code_buf: str = ""

        try:
            async_stream = client.stream_chat_completion(
                prompt_or_messages=messages,
                model=model,
                temperature=0.6,
                top_p=0.9,
                max_tokens=None,
            )

            # bridge async SSE → sync generator
            for token in async_to_sync_stream(async_stream):
                if self.check_cancellation_flag():
                    log.warning(f"Run {run_id} cancelled mid‑stream")
                    yield json.dumps({"type": "error", "content": "Run cancelled"})
                    break

                # ---------- split reasoning tags, if any --------------- #
                segments = (
                    self.REASONING_PATTERN.split(token)
                    if hasattr(self, "REASONING_PATTERN")
                    else [token]
                )
                for seg in segments:
                    if not seg:
                        continue

                    if seg == "<think>":
                        in_reasoning = True
                        reasoning += seg
                        if stream_reasoning:
                            yield json.dumps({"type": "reasoning", "content": seg})
                        continue
                    if seg == "</think>":
                        in_reasoning = False
                        reasoning += seg
                        if stream_reasoning:
                            yield json.dumps({"type": "reasoning", "content": seg})
                        continue

                    # Reasoning branch
                    if in_reasoning:
                        reasoning += seg
                        if stream_reasoning:
                            yield json.dumps({"type": "reasoning", "content": seg})
                        continue

                    # Visible assistant text
                    assistant_reply += seg
                    accumulated += seg

                    # --- code‑interpreter hot‑path -------------------- #
                    partial_match = (
                        self.parse_code_interpreter_partial(accumulated)
                        if hasattr(self, "parse_code_interpreter_partial")
                        else None
                    )

                    if not code_mode and partial_match:
                        # a full ```python …``` block just finished
                        full = partial_match.get("full_match")
                        if full and full in accumulated:
                            accumulated = accumulated.split(full, 1)[-1]

                        code_mode = True
                        code_buf = partial_match.get("code", "")
                        self.code_mode = True
                        yield json.dumps({"type": "hot_code", "content": "```python\n"})

                        if code_buf and hasattr(
                            self, "_process_code_interpreter_chunks"
                        ):
                            res, code_buf = self._process_code_interpreter_chunks(
                                "", code_buf
                            )
                            for r in res:
                                yield r
                                assistant_reply += (
                                    r
                                    if isinstance(r, str)
                                    else json.loads(r)["content"]
                                )
                        continue

                    if code_mode:
                        if hasattr(self, "_process_code_interpreter_chunks"):
                            res, code_buf = self._process_code_interpreter_chunks(
                                seg, code_buf
                            )
                            for r in res:
                                yield r
                                assistant_reply += (
                                    r
                                    if isinstance(r, str)
                                    else json.loads(r).get("content", "")
                                )
                        else:
                            yield json.dumps({"type": "hot_code", "content": seg})
                        continue

                    # normal text token
                    if not code_buf:
                        yield json.dumps({"type": "content", "content": seg})

        except Exception as exc:  # pylint: disable=broad-except
            msg = f"DeepSeek client error: {exc}"
            log.error(msg, exc_info=True)
            if hasattr(self, "handle_error"):
                self.handle_error(
                    reasoning + assistant_reply, thread_id, assistant_id, run_id
                )
            yield json.dumps({"type": "error", "content": msg})
            return

        # ---------- conversation bookkeeping -------------------------- #
        if assistant_reply and hasattr(self, "finalize_conversation"):
            self.finalize_conversation(
                reasoning + assistant_reply, thread_id, assistant_id, run_id
            )

        function_call = (
            self.parse_and_set_function_calls(accumulated, assistant_reply)
            if accumulated and hasattr(self, "parse_and_set_function_calls")
            else False
        )

        if function_call:
            self.run_service.update_run_status(
                run_id, ValidationInterface.StatusEnum.pending_action
            )

        if (
            hasattr(self, "run_service")
            and hasattr(ValidationInterface, "StatusEnum")
            and not self.get_function_call_state()
        ):
            self.run_service.update_run_status(
                run_id, ValidationInterface.StatusEnum.completed
            )

        if reasoning:
            log.info(f"Run {run_id}: reasoning tokens = {len(reasoning)}")

    # ------------------------------------------------------------------ #
    # 2)  Function‑calls & helper wrappers
    # ------------------------------------------------------------------ #
    def stream_function_call_output(self, *args, **kwargs):
        """
        Wrapper so BaseInference can call our `.stream()` instead of its own.
        """
        return super().stream_function_call_output(*args, stream=self.stream, **kwargs)

    def process_function_calls(self, *args, **kwargs):
        return super().process_function_calls(*args, **kwargs)

    # ---------- custom conversation wrapper -------------------------- #
    def process_conversation(  # noqa: PLR0913
        self,
        thread_id,
        message_id,
        run_id,
        assistant_id,
        model,
        stream_reasoning=False,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        """
        Custom wrapper that *does not* forward `api_key` to BaseInference
        (it doesn’t know about that kwarg).  We handle the pipeline locally.
        """
        # initial stream
        for chunk in self.stream(
            thread_id=thread_id,
            message_id=message_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=stream_reasoning,
            api_key=api_key,
        ):
            yield chunk

        # function‑call round‑trip
        for chunk in self.process_function_calls(
            thread_id=thread_id,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            api_key=api_key,
        ):
            yield chunk
