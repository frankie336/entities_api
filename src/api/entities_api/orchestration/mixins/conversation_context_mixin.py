"""
All logic that builds the message list passed to the LLM:

• fetch Redis-cached history (or cold-load from DB once)
• inject current assistant tools / instructions
• role-normalisation + truncation
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from projectdavid import Entity

from entities_api.constants.tools import PLATFORM_TOOL_MAP
from entities_api.orchestration.instructions.assembler import \
    assemble_instructions
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ConversationContextMixin:
    _message_cache = None

    @property
    def message_cache(self):
        """
        Fixed: Avoid using Depends() manually.
        Use the sync factory helper instead.
        """
        if not self._message_cache:
            # Import your sync helper (adjust the import path to your project structure)
            from src.api.entities_api.cache.message_cache import \
                get_sync_message_cache

            self._message_cache = get_sync_message_cache()
        return self._message_cache

    @staticmethod
    def _normalize_roles(msgs: List[Dict]) -> List[Dict]:
        """
        Normalizes roles while preserving tool-call metadata.
        """
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
            content = str(raw_content).strip() if raw_content is not None else None

            # 3. Build Base Message
            normalized_msg = {"role": role, "content": content}

            has_tool_calls = False

            # Case A: Tool calls exist as a proper List
            if "tool_calls" in m and m["tool_calls"]:
                normalized_msg["tool_calls"] = m["tool_calls"]
                has_tool_calls = True

            # Case B: Tool calls got flattened into 'content' string (Redis/DB Serialization Bug)
            elif (
                role == "assistant"
                and content
                and isinstance(content, str)
                and content.strip().startswith("[{")
                and "function" in content
            ):
                try:
                    parsed_tools = json.loads(content)
                    if (
                        isinstance(parsed_tools, list)
                        and len(parsed_tools) > 0
                        and "function" in parsed_tools[0]
                    ):
                        normalized_msg["tool_calls"] = parsed_tools
                        has_tool_calls = True
                except (json.JSONDecodeError, TypeError):
                    pass

            # 4. SAFETY LOCK: If tool calls exist, Content MUST be "", NOT None.
            if has_tool_calls:
                normalized_msg["content"] = ""

            # 5. Preserve Tool Response Metadata
            if role == "tool":
                if "tool_call_id" in m and m["tool_call_id"] is not None:
                    normalized_msg["tool_call_id"] = m["tool_call_id"]
                if "name" in m and m["name"]:
                    normalized_msg["name"] = m["name"]

            out.append(normalized_msg)

        return out

    @staticmethod
    def _resolve_and_prioritize_platform_tools(
        tools: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """
        Resolves placeholder tool definitions into concrete platform tools
        and reorders them so Platform tools appear before User tools.

        Robustness:
        - Handles None or empty lists safely.
        - If no placeholders are found, returns the original array structure.
        - Preserves user tool order relative to other user tools.
        """

        # 1. Safety Check: Handle None or empty input
        if not tools:
            return []

        resolved_platform_tools = []
        resolved_user_tools = []

        # 2. Iterate through the inbound tools array
        for tool in tools:
            # Skip invalid entries if the list contains non-dicts
            if not isinstance(tool, dict):
                continue

            tool_type = tool.get("type")

            # Check if it is a placeholder for a platform tool:
            # 1. It exists in our map
            # 2. It isn't explicitly defined as a "function" (user tool)
            # 3. It doesn't have a "function" key (already resolved/defined)
            if (
                tool_type in PLATFORM_TOOL_MAP
                and tool_type != "function"
                and "function" not in tool
            ):
                # It is a placeholder -> Resolve it and bucket as Platform
                resolved_platform_tools.append(PLATFORM_TOOL_MAP[tool_type])
            else:
                # It is a user tool, a custom tool, or a regular function
                # -> Bucket as User (Preserves original object)
                resolved_user_tools.append(tool)

        # 3. MERGE: Platform Tools FIRST, User Tools LAST
        return resolved_platform_tools + resolved_user_tools

    def _build_system_message(self, assistant_id: str) -> Dict:
        """
        Standard System Message Builder.
        Injects Platform Instructions dynamically at runtime.

        Strategy: Append Platform Rules AFTER Developer Instructions to ensure
        technical constraints (like JSON formatting) are strictly enforced.
        """
        cache = self.get_assistant_cache()
        cfg = cache.retrieve_sync(assistant_id)
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Fetch Core Platform Instructions
        # Specifically targeting function calling protocols for Open Source/Non-Native models
        platform_instructions = assemble_instructions(
            include_keys=[
                "TOOL_USAGE_PROTOCOL",
                "FUNCTION_CALL_FORMATTING",
                "FUNCTION_CALL_WRAPPING",
                # Add "validations" or "error_handling" here if globally required
            ]
        )

        # 2. Get Developer Instructions
        developer_instructions = cfg.get("instructions", "")

        # 3. Resolve and prepend selected platform tools

        final_tools = self._resolve_and_prioritize_platform_tools(tools=cfg["tools"])

        # 4. Assemble Payload
        # Hierarchy: [Context] -> [Persona] -> [Platform Protocols] -> [Tools]
        combined_content = (
            f"Today's date and time: {today}\n\n"
            f"### ASSISTANT INSTRUCTIONS\n"
            f"{developer_instructions}\n\n"
            f"### OPERATIONAL PROTOCOLS\n"
            f"{platform_instructions}\n\n"
            f"### AVAILABLE TOOLS\n"
            f"tools:\n{json.dumps(final_tools)}"
        )

        return {
            "role": "system",
            "content": combined_content,
        }

    # TODO: To be decommissioned
    def _build_amended_system_message(self, assistant_id: str) -> Dict:
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

    def _build_native_function_calls_system_message(self, assistant_id: str) -> Dict:
        """
        Amended for models that have native function call format.
        Standard System Message Builder.
        Injects Platform Instructions dynamically at runtime.

        Strategy: Append Platform Rules AFTER Developer Instructions to ensure
        echnical constraints (like JSON formatting) are strictly enforced.
        """
        cache = self.get_assistant_cache()
        cfg = cache.retrieve_sync(assistant_id)
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Fetch Core Platform Instructions
        # Specifically targeting function calling protocols for Open Source/Non-Native models
        platform_instructions = assemble_instructions(
            include_keys=[
                # "TOOL_USAGE_PROTOCOL",
                # "FUNCTION_CALL_FORMATTING",
                # "FUNCTION_CALL_WRAPPING",
                "DEVELOPER_INSTRUCTIONS"  # <- In reality is an empty dummy instruction
            ]
        )

        # 2. Get Developer Instructions
        developer_instructions = cfg.get("instructions", "")

        # 3. Resolve and prepend selected platform tools

        final_tools = self._resolve_and_prioritize_platform_tools(tools=cfg["tools"])

        # 4. Assemble Payload
        # Hierarchy: [Context] -> [Persona] -> [Platform Protocols] -> [Tools]
        combined_content = (
            f"Today's date and time: {today}\n\n"
            f"### ASSISTANT INSTRUCTIONS\n"
            f"{developer_instructions}\n\n"
            f"### OPERATIONAL PROTOCOLS\n"
            f"{platform_instructions}\n\n"
            f"### AVAILABLE TOOLS\n"
            f"tools:\n{json.dumps(final_tools)}"
        )

        return {
            "role": "system",
            "content": combined_content,
        }

    def _set_up_context_window(
        self,
        assistant_id: str,
        thread_id: str,
        trunk: Optional[bool] = True,
        structured_tool_call: Optional[bool] = False,
        force_refresh: Optional[bool] = False,
    ) -> List[Dict]:
        """
        Synchronous context window setup with integrated Refresh & Cache debugging.
        """
        # 1. Build System Message
        if structured_tool_call:
            system_msg = self._build_native_function_calls_system_message(assistant_id)
        else:
            system_msg = self._build_system_message(assistant_id)

        # 2. Get history using the SYNC helper
        if force_refresh:
            LOG.debug(f"[CTX-REFRESH] 🔄 Force Refresh Active for {thread_id}")
            client = Entity(
                base_url=os.getenv("ASSISTANTS_BASE_URL"),
                api_key=os.getenv("ADMIN_API_KEY"),
            )

            # Fetch fresh list from DB
            full_hist = client.messages.get_formatted_messages(
                thread_id,
                system_message=None,
            )

            # --- DEBUG: DB VERIFICATION ---
            import json

            last_role = full_hist[-1].get("role") if full_hist else "N/A"
            LOG.info(
                f"[CTX-REFRESH] Fresh DB Fetch: {len(full_hist)} msgs | Last Role: {last_role}"
            )
            LOG.debug(f"[CTX-REFRESH] DB Content: {json.dumps(full_hist, indent=2)}")

            # Sync the cache
            self.message_cache.set_history_sync(thread_id, full_hist)
            msgs = full_hist
        else:
            # Standard path: hit Redis first
            msgs = self.message_cache.get_history_sync(thread_id)
            LOG.debug(f"[CTX-CACHE] Redis Hit for {thread_id}: {len(msgs)} msgs found.")

        # 3. Process Context: Filter system messages and prepend current one
        msgs = [m for m in msgs if m.get("role") != "system"]
        full_context = [system_msg] + msgs

        # 4. Normalization
        normalized = self._normalize_roles(full_context)

        # --- DEBUG: FINAL OUTBOUND PAYLOAD ---
        import json

        LOG.info(
            f"\n=== 🚀 OUTBOUND CONTEXT (Size: {len(normalized)}) ===\n{json.dumps(normalized, indent=2)}\n======================================"
        )

        if trunk:
            return self.conversation_truncator.truncate(normalized)

        return normalized

    def replace_system_message(
        self, context_window: list[dict], new_system_message: str | None = None
    ) -> list[dict]:
        filtered_messages = [msg for msg in context_window if msg["role"] != "system"]
        if new_system_message is not None:
            new_system_msg = {"role": "system", "content": new_system_message}
            filtered_messages.insert(0, new_system_msg)
        return filtered_messages

    def prepare_native_tool_context(
        self, context_window: List[Dict]
    ) -> Tuple[List[Dict], Optional[List[Dict]]]:
        cleaned_ctx = []
        extracted_tools = None

        for msg in context_window:
            role = msg.get("role")
            content = msg.get("content") or ""
            new_msg = dict(msg)

            if role == "system" and "tools:\n[" in content:
                try:
                    parts = content.split("tools:\n", 1)
                    system_text = parts[0].strip()
                    tools_json_str = parts[1].strip()

                    if "\n" in tools_json_str:
                        json_part, instructions_part = tools_json_str.split("\n", 1)
                        extracted_tools = json.loads(json_part)
                        new_msg["content"] = (
                            f"{system_text}\n{instructions_part}".strip()
                        )
                    else:
                        extracted_tools = json.loads(tools_json_str)
                        new_msg["content"] = (
                            system_text or "You are a helpful assistant."
                        )
                except Exception as e:
                    LOG.error(f"[CTX-MIXIN] Failed tool extraction: {e}")

            if role == "tool" and not isinstance(content, str):
                new_msg["content"] = json.dumps(content)

            cleaned_ctx.append(new_msg)

        return cleaned_ctx, extracted_tools
