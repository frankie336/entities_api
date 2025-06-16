"""
All generic streaming helpers shared by every provider:

• start_cancellation_listener — fire-and-forget thread
• _shunt_to_redis_stream      — mirror chunks for other workers
• _process_code_interpreter_chunks — line-wise splitter for ```python``` previews
• stream_function_call_output — injects reminders & SSE proxy
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable, Generator, Optional

import redis as redis_py

from entities_api.constants.assistant import (CODE_INTERPRETER_MESSAGE,
                                              DEFAULT_REMINDER_MESSAGE)
from entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class StreamingMixin:
    # the concrete provider sets `self.redis` on __init__
    redis: redis_py.Redis

    # ------------------------------------------------------------------ #
    # Cancellation listener (non-blocking flag)                          #
    # ------------------------------------------------------------------ #
    _cancelled: bool = False

    def start_cancellation_listener(self, run_id: str, poll_interval: float = 1.0):
        """
        Spawns a *daemon* thread that flips `self._cancelled`
        whenever a “cancelled” event appears in the run table.
        """
        from projectdavid import Entity

        from entities_api.services.event_handler import EntitiesEventHandler

        if getattr(self, "_cancellation_thread", None):
            if self._cancellation_thread.is_alive():  # type: ignore[attr-defined]
                return

        pd_client = Entity(
            api_key=os.getenv("ADMIN_API_KEY"),
            base_url=os.getenv("BASE_URL"),
        )

        def handle(evt_type, _):
            return evt_type == "cancelled"

        def loop():
            handler = EntitiesEventHandler(
                run_service=pd_client.runs,
                action_service=pd_client.actions,
                event_callback=handle,
            )
            while not self._cancelled:
                if handler._emit_event("cancelled", run_id):
                    self._cancelled = True
                    LOG.info("Run %s was cancelled by user", run_id)
                    break
                time.sleep(poll_interval)

        self._cancellation_thread = threading.Thread(target=loop, daemon=True)
        self._cancellation_thread.start()

    def check_cancellation_flag(self) -> bool:
        return self._cancelled

    # ------------------------------------------------------------------ #
    # Redis side-channel helper                                          #
    # ------------------------------------------------------------------ #
    def _shunt_to_redis_stream(
        self, redis, stream_key, chunk_dict, *, maxlen=1000, ttl_seconds=3600
    ):
        try:
            # ----------------------------------------------------------
            # Guard: skip if we didn’t get a *sync* redis client
            # ----------------------------------------------------------
            if not callable(getattr(redis, "xadd", None)):
                LOG.debug("[Redis Shunt] async or stub Redis – skipping XADD")
                return

            if isinstance(chunk_dict, str):
                chunk_dict = json.loads(chunk_dict)

            redis.xadd(stream_key, chunk_dict, maxlen=maxlen, approximate=True)

            if not redis.exists(f"{stream_key}::ttl_set"):
                redis.expire(stream_key, ttl_seconds)
                redis.set(f"{stream_key}::ttl_set", "1", ex=ttl_seconds)

        except Exception as exc:
            LOG.warning(
                "[Redis Shunt] failed (%s): %s", type(exc).__name__, exc, exc_info=True
            )

    # ------------------------------------------------------------------ #
    # Helper used by providers when they detect ```python``` blocks      #
    # ------------------------------------------------------------------ #
    def _process_code_interpreter_chunks(self, content_chunk, code_buffer):
        """
        Process code chunks while in code mode.

        Appends the incoming content_chunk to code_buffer,
        then extracts a single line (if a newline exists) and handles buffer overflow.

        Returns:
            tuple: (results, updated code_buffer)
                - results: list of JSON strings representing code chunks.
                - updated code_buffer: the remaining buffer content.
        """

        self.code_mode = True

        results = []
        code_buffer += content_chunk

        # Process one line at a time if a newline is present.
        if "\n" in code_buffer:
            newline_pos = code_buffer.find("\n") + 1
            line_chunk = code_buffer[:newline_pos]
            code_buffer = code_buffer[newline_pos:]
            # Optionally, you can add security checks here for forbidden patterns.
            results.append(json.dumps({"type": "hot_code", "content": line_chunk}))

        # Buffer overflow protection: if the code_buffer grows too large,
        # yield its content as a chunk and reset it.
        if len(code_buffer) > 100:
            results.append(json.dumps({"type": "hot_code", "content": code_buffer}))
            code_buffer = ""

        return results, code_buffer

    # ------------------------------------------------------------------ #
    # Generic “reminder → stream → finalise” wrapper                     #
    # ------------------------------------------------------------------ #
    def stream_function_call_output(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        model: str,
        *,
        stream: Callable[..., Generator[str, None, None]],
        name: Optional[str] = None,
        stream_reasoning: bool = False,
        api_key: Optional[str] = None,
    ):
        """
        Injects a short reminder (“You are now executing code …”) so the
        assistant does not hallucinate, then transparently proxies the
        underlying provider stream to the client **and** Redis.
        """
        # 0 decide which reminder
        reminder = (
            CODE_INTERPRETER_MESSAGE
            if name == "code_interpreter"
            else DEFAULT_REMINDER_MESSAGE
        )

        # 1 push reminder into the thread
        self.project_david_client.messages.create_message(  # type: ignore[attr-defined]
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=reminder,
            role="user",
        )

        # 2 open sub-stream
        gen = stream(
            thread_id=thread_id,
            message_id=None,
            run_id=run_id,
            assistant_id=assistant_id,
            model=model,
            stream_reasoning=True,
            api_key=api_key,
        )

        redis_key = f"stream:{run_id}"
        assistant_reply = ""
        reasoning = ""

        for raw in gen:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                parsed = {"type": "content", "content": str(raw)}

            t = parsed.get("type")
            c = parsed.get("content", "")

            if t == "reasoning":
                reasoning += c
            elif t == "content":
                assistant_reply += c

            yield raw
            self._shunt_to_redis_stream(self.redis, redis_key, parsed)

        # 3 final bookkeeping
        if assistant_reply:
            self.finalize_conversation(  # type: ignore[attr-defined]
                reasoning + assistant_reply, thread_id, assistant_id, run_id
            )
