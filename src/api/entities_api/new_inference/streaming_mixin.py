# streaming_mixin.py

import json
import time
from abc import ABC, abstractmethod
from collections import deque
from threading import Thread
from typing import Any, Callable, Dict, Generator, Optional


class StreamingMixin(ABC):
    @abstractmethod
    def stream_function_call_output(
        self,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        stream_reasoning: bool,
        api_key: Optional[str],
    ) -> Generator[str, None, None]:
        """Must be implemented by the inheriting class."""
        pass

    @abstractmethod
    def _get_project_david_client(
        self, api_key: Optional[str], base_url: Optional[str]
    ) -> Any:
        """Must be implemented by the inheriting class."""
        pass

    def _stream_with_function_call_buffer(
        self,
        response: Any,
        thread_id: str,
        run_id: str,
        assistant_id: str,
        model: Any,
        stream_reasoning: bool,
        api_key: Optional[str],
        redis,
        stream_key: str,
        max_buffer_chars: int = 4096,
    ) -> Generator[str, None, None]:
        def _handle_candidate(candidate: str) -> Generator[str, None, None]:
            try:
                obj = json.loads(candidate)
            except (ValueError, TypeError):
                chunk = {"type": "content", "content": candidate}
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)
            else:
                if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                    yield from self.stream_function_call_output(
                        thread_id=thread_id,
                        run_id=run_id,
                        assistant_id=assistant_id,
                        model=model,
                        stream_reasoning=stream_reasoning,
                        api_key=api_key,
                    )
                else:
                    chunk = {"type": "content", "content": candidate}
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)

        buffer = deque()
        brace_count = 0
        parsing_json = False

        for token in response:
            text = getattr(token.choices[0].delta, "content", "")
            if not text:
                continue

            if not parsing_json:
                stripped = text.lstrip()
                if stripped.startswith("{"):
                    parsing_json = True
                    buffer.append(text)
                    for ch in stripped:
                        brace_count += ch == "{" or -1 * (ch == "}")
                    if brace_count == 0:
                        yield from _handle_candidate("".join(buffer))
                        buffer.clear()
                        parsing_json = False
                    continue
                else:
                    chunk = {"type": "content", "content": text}
                    yield json.dumps(chunk)
                    self._shunt_to_redis_stream(redis, stream_key, chunk)
                    continue

            buffer.append(text)
            for ch in text:
                brace_count += ch == "{" or -1 * (ch == "}")

            if brace_count == 0:
                yield from _handle_candidate("".join(buffer))
                buffer.clear()
                parsing_json = False

            if sum(len(part) for part in buffer) > max_buffer_chars:
                leftover = "".join(buffer)
                chunk = {"type": "content", "content": leftover}
                yield json.dumps(chunk)
                self._shunt_to_redis_stream(redis, stream_key, chunk)
                buffer.clear()
                brace_count = 0
                parsing_json = False

    def _shunt_to_redis_stream(
        self, redis, stream_key, chunk_dict, *, maxlen=1000, ttl_seconds=3600
    ):
        try:
            if isinstance(chunk_dict, str):
                chunk_dict = json.loads(chunk_dict)

            redis.xadd(stream_key, chunk_dict, maxlen=maxlen, approximate=True)

            if not redis.exists(f"{stream_key}::ttl_set"):
                redis.expire(stream_key, ttl_seconds)
                redis.set(f"{stream_key}::ttl_set", "1", ex=ttl_seconds)

        except Exception as e:
            from entities_api.services.logging_service import LoggingUtility

            LoggingUtility().warning(
                f"[Redis Shunt] Failed to XADD or EXPIRE {stream_key}: {e}",
                exc_info=True,
            )

    def start_cancellation_listener(
        self, run_id: str, poll_interval: float = 1.0
    ) -> None:
        if (
            hasattr(self, "_cancellation_thread")
            and self._cancellation_thread.is_alive()
        ):
            return

        def handle_event(event_type: str, event_data: Any):
            if event_type == "cancelled":
                return "cancelled"

        client = self._get_project_david_client(
            api_key=self.api_key, base_url=self.base_url
        )

        def listen_for_cancellation():
            from entities_api.services.event_handler import EntitiesEventHandler

            event_handler = EntitiesEventHandler(
                run_service=client.runs,
                action_service=client.actions,
                event_callback=handle_event,
            )
            while not self._cancelled:
                if event_handler._emit_event("cancelled", run_id) == "cancelled":
                    self._cancelled = True
                    break
                time.sleep(poll_interval)

        self._cancellation_thread = Thread(target=listen_for_cancellation, daemon=True)
        self._cancellation_thread.start()

    def check_cancellation_flag(self) -> bool:
        return getattr(self, "_cancelled", False)
