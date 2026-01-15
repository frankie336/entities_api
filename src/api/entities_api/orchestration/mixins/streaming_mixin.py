"""
All generic streaming helpers shared by every provider:

• start_cancellation_listener — fire-and-forget thread
• _shunt_to_redis_stream      — mirror chunks for other workers
• _process_code_interpreter_chunks — line-wise splitter for ```python``` previews
• stream_function_call_output — injects reminders & SSE proxy
"""

from __future__ import annotations

import json
import time
from threading import Event, Thread
from typing import Callable, Generator, Optional

import redis as redis_py

from src.api.entities_api.constants.assistant import (
    CODE_INTERPRETER_MESSAGE,
    DEFAULT_REMINDER_MESSAGE,
)
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class StreamingMixin:
    redis: redis_py.Redis
    _cancelled: bool = False

    def start_cancellation_monitor(self, run_id: str, interval: float = 1.0) -> Event:
        """
        Spawns a daemon thread that watches the run status via the SDK.
        If the run is marked `cancelled`, we flip an Event flag.
        Returns the Event instance to be shared with the streaming loop.
        """
        stop_event = Event()

        def monitor():
            while not stop_event.is_set():
                try:
                    run = self.project_david_client.runs.retrieve_run(run_id)
                    if run.status == "cancelled":
                        LOG.warning("Run %s was cancelled via API.", run_id)
                        stop_event.set()
                        break
                except Exception as e:
                    LOG.warning("Cancellation monitor error: %s", e)
                time.sleep(interval)

        Thread(target=monitor, daemon=True).start()
        return stop_event

    def check_cancellation_flag(self) -> bool:
        return self._cancelled

    def _shunt_to_redis_stream(
        self, redis, stream_key, chunk_dict, *, maxlen=1000, ttl_seconds=3600
    ):
        try:
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
        if "\n" in code_buffer:
            newline_pos = code_buffer.find("\n") + 1
            line_chunk = code_buffer[:newline_pos]
            code_buffer = code_buffer[newline_pos:]
            results.append(json.dumps({"type": "hot_code", "content": line_chunk}))
        if len(code_buffer) > 100:
            results.append(json.dumps({"type": "hot_code", "content": code_buffer}))
            code_buffer = ""
        return (results, code_buffer)

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
        reminder = (
            CODE_INTERPRETER_MESSAGE
            if name == "code_interpreter"
            else DEFAULT_REMINDER_MESSAGE
        )
        self.project_david_client.messages.create_message(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=reminder,
            role="user",
        )
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
        if assistant_reply:
            self.finalize_conversation(
                reasoning + assistant_reply, thread_id, assistant_id, run_id
            )
