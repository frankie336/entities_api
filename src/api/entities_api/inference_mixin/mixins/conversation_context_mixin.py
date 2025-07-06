"""
All logic that builds the message list passed to the LLM:

• fetch Redis-cached history (or cold-load from DB once)
• inject current assistant tools / instructions
• role-normalisation + truncation
"""

import json
import os
from datetime import datetime
from typing import Dict, List

from projectdavid import Entity

from src.api.entities_api.services.logging_service import LoggingUtility
from src.api.entities_api.system_message.main_assembly import \
    assemble_instructions

LOG = LoggingUtility()


class ConversationContextMixin:

    @staticmethod
    def _normalize_roles(msgs: List[Dict]) -> List[Dict]:
        out: List[Dict] = []
        for m in msgs:
            role = str(m.get("role", "user")).lower()
            if role not in ("user", "assistant", "system", "tool", "platform"):
                role = "user"
            out.append({"role": role, "content": str(m.get("content", "")).strip()})
        return out

    def _build_system_message(self, assistant_id: str) -> Dict:
        """
        Pull the assistant’s cached tool list + instructions through
        AssistantCacheMixin’s accessor, then craft the final system prompt.
        """
        cache = self.get_assistant_cache()
        cfg = cache.retrieve_sync(assistant_id)
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "role": "system",
            "content": f"tools:\n{json.dumps(cfg['tools'])}\n{cfg['instructions']}\nToday's date and time: {today}",
        }

    def _build_amended_system_message(self, assistant_id: str) -> Dict:
        """
        Use to build alternative system message for R1
        """
        cache = self.get_assistant_cache()
        cfg = cache.retrieve_sync(assistant_id)
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        excluded_instructions = assemble_instructions(
            exclude_keys=["TOOL_USAGE_PROTOCOL"]
        )
        return {
            "role": "system",
            "content": f"tools:\n{json.dumps(cfg['tools'])}\n{excluded_instructions}\nToday's date and time: {today}",
        }

    def _set_up_context_window(
        self, assistant_id: str, thread_id: str, trunk: bool = True
    ):
        """Prepares and optimizes conversation context for model processing.

        Constructs the conversation history while ensuring it fits within the model's
        context window limits through intelligent truncation. Combines multiple elements
        to create rich context:
        - Assistant's configured tools
        - Current instructions
        - Temporal awareness (today's date)
        - Complete conversation history

        Args:
            assistant_id (str): UUID of the assistant profile to retrieve tools/instructions
            thread_id (str): UUID of conversation thread for message history retrieval
            trunk (bool): Enable context window optimization via truncation (default: True)

        Returns:
            list: Processed message list containing either:
                - Truncated messages (if trunk=True)
                - Full normalized messages (if trunk=False)

        Processing Pipeline:
            1. Retrieve assistant configuration and tools
            2. Fetch complete conversation history
            3. Inject system message with:
               - Active tools list
               - Current instructions
               - Temporal context (today's date)
            4. Normalize message roles for API consistency
            5. Apply sliding window truncation when enabled

        Note:
            Uses LRU-cached service calls for assistant/message retrieval to optimize
            repeated requests with identical parameters.
        """
        system_msg = self._build_system_message(assistant_id)
        redis_key = f"thread:{thread_id}:history"
        raw_list = self.redis.lrange(redis_key, 0, -1)
        if not raw_list:
            client = Entity(
                base_url=os.getenv("ASSISTANTS_BASE_URL"),
                api_key=os.getenv("ADMIN_API_KEY"),
            )
            full_hist = client.messages.get_formatted_messages(
                thread_id, system_message=system_msg["content"]
            )
            for msg in full_hist[-200:]:
                self.redis.rpush(redis_key, json.dumps(msg))
            self.redis.ltrim(redis_key, -200, -1)
            raw_list = [json.dumps(m) for m in full_hist]
        msgs = [system_msg] + [json.loads(x) for x in raw_list]
        normalized = self._normalize_roles(msgs)
        return self.conversation_truncator.truncate(normalized) if trunk else normalized

    def replace_system_message(
        self, context_window: list[dict], new_system_message: str | None = None
    ) -> list[dict]:
        """
        Removes the existing system message and optionally replaces it with a new one.

        Args:
            context_window: Output from `_set_up_context_window`.
            new_system_message: Content of the replacement system message (if None, just remove the old one).

        Returns:
            Updated context window without the original system message (and optionally a new one).
        """
        filtered_messages = [msg for msg in context_window if msg["role"] != "system"]
        if new_system_message is not None:
            new_system_msg = {"role": "system", "content": new_system_message}
            filtered_messages.insert(0, new_system_msg)
        return filtered_messages
