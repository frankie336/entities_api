"""
All logic that builds the message list passed to the LLM:

• fetch Redis-cached history (or cold-load from DB once)
• inject current assistant tools / instructions
• role-normalisation + truncation
"""

from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()

"""
All logic that builds the message list passed to the LLM:

• fetch Redis-cached history (or cold-load from DB once)
• inject current assistant tools / instructions
• role-normalisation + truncation
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from projectdavid import Entity

from src.api.entities_api.services.logging_service import LoggingUtility
from src.api.entities_api.system_message.main_assembly import \
    assemble_instructions

LOG = LoggingUtility()


class ConversationContextMixin:

    @staticmethod
    def _normalize_roles(msgs: List[Dict]) -> List[Dict]:
        """
        Normalizes roles while preserving tool-call metadata.
        FIXED: Handles serialization errors AND ensures content is "" (not None).
        """
        import json

        out: List[Dict] = []

        for m in msgs:
            # 1. Standardize Role
            raw_role = str(m.get("role", "user")).lower()
            role = (
                raw_role
                if raw_role in ("user", "assistant", "system", "tool", "platform")
                else "user"
            )

            # 2. Extract Content
            raw_content = m.get("content")
            # Default to None if missing, strip if string
            content = str(raw_content).strip() if raw_content is not None else None

            # 3. Build Base Message
            normalized_msg = {"role": role, "content": content}

            # --- LOGIC FIX START ---

            has_tool_calls = False

            # Case A: Tool calls exist as a proper List (Memory / Correct DB)
            if "tool_calls" in m and m["tool_calls"]:
                normalized_msg["tool_calls"] = m["tool_calls"]
                has_tool_calls = True

            # Case B: Tool calls got flattened into 'content' string (Redis/DB Serialization Bug)
            # We detect this by checking if content looks like a JSON array of functions
            elif (
                role == "assistant"
                and content
                and isinstance(content, str)
                and content.strip().startswith("[{")
                and "function" in content  # heuristic check
            ):
                try:
                    parsed_tools = json.loads(content)
                    # Validate it's actually a list of tool calls
                    if (
                        isinstance(parsed_tools, list)
                        and len(parsed_tools) > 0
                        and "function" in parsed_tools[0]
                    ):
                        normalized_msg["tool_calls"] = parsed_tools
                        has_tool_calls = True
                except (json.JSONDecodeError, TypeError):
                    # It was just a user saying "[{...}]" literally, ignore.
                    pass

            # 4. SAFETY LOCK: strict API requirement
            # If tool calls exist, Content MUST be an empty string "", NOT None.
            if has_tool_calls:
                normalized_msg["content"] = ""

                # --- LOGIC FIX END ---

            # 5. Preserve Tool Response Metadata
            if "tool_call_id" in m:
                normalized_msg["tool_call_id"] = m["tool_call_id"]

            if "name" in m:
                normalized_msg["name"] = m["name"]

            out.append(normalized_msg)

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

    def _build_native_tools_system_message(self, assistant_id: str) -> Dict:
        """
        Use to build  system message for models with native tool channels, eg gpt-oss
        """

        # The assistant cache contains the system message and tools per assistant
        cache = self.get_assistant_cache()

        cfg = cache.retrieve_sync(assistant_id)
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        excluded_instructions = assemble_instructions(
            exclude_keys=[
                "TOOL_USAGE_PROTOCOL",
                "FUNCTION_CALL_FORMATTING",
                "FUNCTION_CALL_WRAPPING",
                # "CODE_INTERPRETER",
                "TERMINATION_CONDITIONS",
                "ADVANCED_ANALYSIS",
                "VECTOR_SEARCH_COMMANDMENTS",
                "VECTOR_SEARCH_EXAMPLES",
                "WEB_SEARCH_RULES",
                "QUERY_OPTIMIZATION",
                "RESULT_CURATION",
                "VALIDATION_IMPERATIVES",
                "TERMINATION_CONDITIONS",
                "ERROR_HANDLING",
                "OUTPUT_FORMAT_RULES",
                "LATEX_MARKDOWN_FORMATTING",
                "INTERNAL_REASONING_PROTOCOL",
                "MUSIC_NOTATION_GUIDELINES",
                "FINAL_WARNING",
                "USER_DEFINED_INSTRUCTIONS",
            ]
        )
        return {
            "role": "system",
            "content": f"tools:\n{json.dumps(cfg['tools'])}\n{excluded_instructions}\nToday's date and time: {today}",
        }

    def _set_up_context_window(
        self,
        assistant_id: str,
        thread_id: str,
        trunk: Optional[bool] = True,
        tools_native: Optional[bool] = False,
        # Default False = Use Redis Cache (Efficient).
        # Set True = Ignore Redis, Hit DB (Accurate for Turn 2).
        force_refresh: Optional[bool] = False,
    ):
        """Prepares context window with optional cache invalidation."""

        if tools_native:
            system_msg = self._build_native_tools_system_message(assistant_id)
        else:
            system_msg = self._build_system_message(assistant_id)

        redis_key = f"thread:{thread_id}:history"
        raw_list = []

        # 1. Check Redis (only if NOT forcing a refresh)
        if not force_refresh:
            raw_list = self.redis.lrange(redis_key, 0, -1)
            # LOG.debug(f"[CTX] Redis Hit: {bool(raw_list)}")

        # 2. Fetch from DB if cache missed OR force_refresh was requested
        if not raw_list:
            if force_refresh:
                LOG.debug(
                    f"[CTX] Force Refresh Active. Bypassing Redis for {thread_id}"
                )
            else:
                LOG.debug(f"[CTX] Redis Miss. Fetching DB for {thread_id}")

            client = Entity(
                base_url=os.getenv("ASSISTANTS_BASE_URL"),
                api_key=os.getenv("ADMIN_API_KEY"),
            )

            # Fetch fresh list (includes new Tool Messages saved by ActionService)
            full_hist = client.messages.get_formatted_messages(
                thread_id,
                system_message=None,
            )

            # Re-populate Redis
            self.redis.delete(redis_key)
            for msg in full_hist[-200:]:
                self.redis.rpush(redis_key, json.dumps(msg))
            self.redis.ltrim(redis_key, -200, -1)
            raw_list = [json.dumps(m) for m in full_hist]

        # Decode
        msgs = [json.loads(x) for x in raw_list]

        # Deduplicate System Messages
        msgs = [m for m in msgs if m.get("role") != "system"]

        # Prepend Context System Message
        msgs = [system_msg] + msgs
        # msgs = msgs

        # Normalization & Truncation
        normalized = self._normalize_roles(msgs)

        if trunk:
            return self.conversation_truncator.truncate(normalized)

        return normalized

    def old_set_up_context_window(
        self,
        assistant_id: str,
        thread_id: str,
        trunk: bool = True,
        tools_native: bool = False,
        force_refresh: Optional[bool] = False,
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
        if tools_native:
            system_msg = self._build_native_tools_system_message(assistant_id)
        else:
            system_msg = self._build_system_message(assistant_id)

        redis_key = f"thread:{thread_id}:history"

        # 1. Check Redis (only if NOT forcing a refresh)
        if not force_refresh:
            raw_list = self.redis.lrange(redis_key, 0, -1)
            # LOG.debug(f"[CTX] Redis Hit: {bool(raw_list)}")

        # --- DEBUG LOGGING: REDIS STATE ---
        LOG.debug(f"[CTX-BUILD] Redis Key: {redis_key}")
        LOG.debug(f"[CTX-BUILD] Redis Hit: {bool(raw_list)} | Count: {len(raw_list)}")
        # ----------------------------------

        if not raw_list:
            LOG.debug("[CTX-BUILD] Redis MISS -> Fetching from DB via API...")
            client = Entity(
                base_url=os.getenv("ASSISTANTS_BASE_URL"),
                api_key=os.getenv("ADMIN_API_KEY"),
            )
            full_hist = client.messages.get_formatted_messages(
                thread_id, system_message=system_msg["content"]
            )

            # --- DEBUG LOGGING: DB STATE ---
            LOG.debug(f"[CTX-BUILD] DB Fetch Count: {len(full_hist)}")
            # -------------------------------

            for msg in full_hist[-200:]:
                self.redis.rpush(redis_key, json.dumps(msg))
            self.redis.ltrim(redis_key, -200, -1)
            raw_list = [json.dumps(m) for m in full_hist]

        msgs = [system_msg] + [json.loads(x) for x in raw_list]

        # --- DEBUG LOGGING: PRE-TRUNCATION ---
        debug_roles = [m.get("role") for m in msgs]
        LOG.debug(f"[CTX-BUILD] Pre-Truncation Roles: {debug_roles}")
        # -------------------------------------

        normalized = self._normalize_roles(msgs)

        if trunk:
            truncated = self.conversation_truncator.truncate(normalized)
            LOG.debug(f"[CTX-BUILD] Post-Truncation Count: {len(truncated)}")
            return truncated

        return normalized

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

    def prepare_native_tool_context(
        self, context_window: List[Dict]
    ) -> Tuple[List[Dict], Optional[List[Dict]]]:
        """
        NEW: Performs 'Context Surgery' to extract tool definitions
        from the system message and prepare the context for native tool-calling models.

        Returns:
            (cleaned_ctx, extracted_tools)
        """
        cleaned_ctx = []
        extracted_tools = None

        for msg in context_window:
            role = msg.get("role")
            content = msg.get("content") or ""
            new_msg = dict(msg)  # Clone to avoid mutating original list items

            # 1. Extract tools from system prompt if injected as text by _build_system_message
            if role == "system" and "tools:\n[" in content:
                try:
                    parts = content.split("tools:\n", 1)
                    system_text = parts[0].strip()
                    # Find where the JSON array ends
                    tools_json_str = parts[1].strip()

                    # We assume the Mixin's injection format: tools:\n[...JSON...]\nInstructions
                    # We can use a simple split or more robust JSON detection
                    if "\n" in tools_json_str:
                        json_part, instructions_part = tools_json_str.split("\n", 1)
                        extracted_tools = json.loads(json_part)
                        new_msg["content"] = (
                            f"{system_text}\n{instructions_part}".strip()
                        )
                    else:
                        extracted_tools = json.loads(tools_json_str)
                        new_msg["content"] = (
                            system_text
                            if system_text
                            else "You are a helpful assistant."
                        )
                except Exception as e:
                    LOG.error(f"[CTX-MIXIN] Failed tool extraction: {e}")

            # 2. Stringify tool content (APIs like Hyperbolic require content to be a string)
            if role == "tool" and not isinstance(content, str):
                new_msg["content"] = json.dumps(content)

            cleaned_ctx.append(new_msg)

        return cleaned_ctx, extracted_tools
