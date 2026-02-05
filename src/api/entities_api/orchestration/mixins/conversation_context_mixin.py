import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from projectdavid import Entity

from entities_api.constants.tools import PLATFORM_TOOL_MAP
from entities_api.orchestration.instructions.assembler import \
    assemble_instructions
from src.api.entities_api.orchestration.instructions.assemble_core_instructions import \
    assemble_core_instructions
from src.api.entities_api.orchestration.instructions.include_lists import (
    GENERAL_INSTRUCTIONS, L3_INSTRUCTIONS, NO_CORE_INSTRUCTIONS)
from src.api.entities_api.platform_tools.definitions.record_tool_decision import \
    record_tool_decision
from src.api.entities_api.services.logging_service import LoggingUtility

LOG = LoggingUtility()


class ConversationContextMixin:
    _message_cache = None

    @property
    def message_cache(self):
        if not self._message_cache:
            from src.api.entities_api.cache.message_cache import \
                get_sync_message_cache

            self._message_cache = get_sync_message_cache()
        return self._message_cache

    # -----------------------------------------------------
    # PURE HELPERS (SYNC — unchanged)
    # -----------------------------------------------------

    @staticmethod
    def _normalize_roles(msgs: List[Dict]) -> List[Dict]:
        out: List[Dict] = []

        for m in msgs:
            raw_role = str(m.get("role", "user")).lower()
            role = (
                raw_role
                if raw_role in ("user", "assistant", "system", "tool", "platform")
                else "user"
            )

            raw_content = m.get("content")
            content = str(raw_content).strip() if raw_content is not None else None

            normalized_msg = {"role": role, "content": content}
            has_tool_calls = False

            if "tool_calls" in m and m["tool_calls"]:
                normalized_msg["tool_calls"] = m["tool_calls"]
                has_tool_calls = True

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
                        and parsed_tools
                        and "function" in parsed_tools[0]
                    ):
                        normalized_msg["tool_calls"] = parsed_tools
                        has_tool_calls = True
                except (json.JSONDecodeError, TypeError):
                    pass

            if has_tool_calls:
                normalized_msg["content"] = ""

            if role == "tool":
                if m.get("tool_call_id") is not None:
                    normalized_msg["tool_call_id"] = m["tool_call_id"]
                if m.get("name"):
                    normalized_msg["name"] = m["name"]

            out.append(normalized_msg)

        return out

    @staticmethod
    def _resolve_and_prioritize_platform_tools(
        tools: Optional[List[Dict[str, Any]]],
        *,
        decision_telemetry: bool = True,
    ) -> List[Dict[str, Any]]:

        mandatory_platform_tools = []
        if decision_telemetry:
            mandatory_platform_tools.append(record_tool_decision)

        tools = tools or []

        resolved_platform_tools = []
        resolved_user_tools = []

        for tool in tools:
            if not isinstance(tool, dict):
                continue

            tool_type = tool.get("type")

            if (
                tool_type in PLATFORM_TOOL_MAP
                and tool_type != "function"
                and "function" not in tool
            ):
                resolved_platform_tools.append(PLATFORM_TOOL_MAP[tool_type])
            else:
                resolved_user_tools.append(tool)

        platform_tools_all = mandatory_platform_tools + resolved_platform_tools

        seen_names = set()
        deduped_platform_tools = []

        for tool in platform_tools_all:
            try:
                name = tool["function"]["name"]
            except KeyError:
                continue

            if name not in seen_names:
                seen_names.add(name)
                deduped_platform_tools.append(tool)

        return deduped_platform_tools + resolved_user_tools

    # -----------------------------------------------------
    # ASYNC BUILDERS (FIXED)
    # -----------------------------------------------------

    async def _build_system_message(
        self,
        assistant_id: str,
        decision_telemetry: bool = True,
        agent_mode: bool = False,
    ) -> Dict:

        cache = self.get_assistant_cache()
        cfg = await cache.retrieve(assistant_id)

        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ---------------------------------------------------------
        # 1. Builds core platform instructions
        # 2. Merges Core instructions with developer instructions
        # 2. If model tolerates decision telemetry in insert the instruction
        # 3. Preserves the order: [platform_instructions]
        #                          [developer_instruction]
        # ----------------------------------------------------------

        if agent_mode:
            instructions = L3_INSTRUCTIONS
        else:
            instructions = GENERAL_INSTRUCTIONS

        platform_instructions = await assemble_core_instructions(
            include_keys=instructions, decision_telemetry=decision_telemetry
        )

        developer_instructions = cfg.get("instructions", "")

        # -------------------------------------------------
        # - Resolves the assistants tools registry
        # - Merges The assistants tools registry
        # with selected platform tools
        # -----------------------------------------------------
        final_tools = self._resolve_and_prioritize_platform_tools(
            tools=cfg["tools"],
            decision_telemetry=decision_telemetry,
        )

        combined_content = (
            f"Today's date and time: {today}\n\n"
            f"### ASSISTANT INSTRUCTIONS\n"
            f"{developer_instructions}\n\n"
            f"### OPERATIONAL PROTOCOLS\n"
            f"{platform_instructions}\n\n"
            f"### AVAILABLE TOOLS\n"
            f"tools:\n{json.dumps(final_tools)}"
        )

        return {"role": "system", "content": combined_content}

    async def _build_amended_system_message(self, assistant_id: str) -> Dict:
        cache = self.get_assistant_cache()
        cfg = await cache.retrieve(assistant_id)

        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        excluded_instructions = assemble_instructions(
            exclude_keys=["TOOL_USAGE_PROTOCOL"]
        )

        return {
            "role": "system",
            "content": f"tools:\n{json.dumps(cfg['tools'])}\n{excluded_instructions}\nToday's date and time: {today}",
        }

    async def _build_native_function_calls_system_message(
        self,
        assistant_id: str,
        decision_telemetry: bool = True,
        agent_mode: bool = False,
    ) -> Dict:

        cache = self.get_assistant_cache()
        cfg = await cache.retrieve(assistant_id)

        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if agent_mode:
            instructions = L3_INSTRUCTIONS
        else:
            instructions = GENERAL_INSTRUCTIONS

        platform_instructions = await assemble_core_instructions(
            include_keys=instructions, decision_telemetry=decision_telemetry
        )

        developer_instructions = cfg.get("instructions", "")

        final_tools = self._resolve_and_prioritize_platform_tools(
            tools=cfg["tools"],
            decision_telemetry=decision_telemetry,
        )

        combined_content = (
            f"Today's date and time: {today}\n\n"
            f"### ASSISTANT INSTRUCTIONS\n"
            f"{developer_instructions}\n\n"
            f"### OPERATIONAL PROTOCOLS\n"
            f"{platform_instructions}\n\n"
            f"### AVAILABLE TOOLS\n"
            f"tools:\n{json.dumps(final_tools)}"
        )

        return {"role": "system", "content": combined_content}

    # -----------------------------------------------------
    # ASYNC CONTEXT WINDOW (FIXED)
    # -----------------------------------------------------

    async def _set_up_context_window(
        self,
        assistant_id: str,
        thread_id: str,
        trunk: Optional[bool] = True,
        structured_tool_call: Optional[bool] = False,
        force_refresh: Optional[bool] = False,
        decision_telemetry: bool = True,
        agent_mode: bool = False,
    ) -> List[Dict]:

        # 1. Build the System Message (This part is solid)
        if structured_tool_call:
            system_msg = await self._build_native_function_calls_system_message(
                assistant_id=assistant_id,
                decision_telemetry=decision_telemetry,
                agent_mode=agent_mode,
            )
        else:
            system_msg = await self._build_system_message(
                assistant_id=assistant_id,
                decision_telemetry=decision_telemetry,
                agent_mode=agent_mode,
            )

        if force_refresh:
            LOG.debug(f"[CTX-REFRESH] 🔄 Force Refresh Active for {thread_id}")

            # --- CRITICAL CHANGE START: BYPASS HTTP ---
            # Instead of: client = Entity(...), use the internal service directly.
            # Assuming you have self.message_service or similar available via the Mixin.

            # If you don't have the service injected, utilize the direct DB lookup logic
            # that your 'get_formatted_messages' endpoint uses.

            try:
                # Bypass the HTTP request to prevent deadlock
                full_hist = await asyncio.to_thread(
                    self.message_service.get_formatted_messages,  # Use the SERVICE, not the CLIENT
                    thread_id=thread_id,
                    system_message=None,
                )
            except AttributeError:
                # Fallback: If service isn't available, we MUST increase the timeout
                # and use a non-blocking internal URL.
                LOG.warning(
                    "[CTX-REFRESH] Service not found, falling back to internal API (Danger of Deadlock)"
                )
                client = Entity(
                    base_url="http://localhost:9000",  # Ensure this points to the internal network
                    api_key=os.getenv("ADMIN_API_KEY"),
                )
                full_hist = client.messages.get_formatted_messages(
                    thread_id, system_message=None
                )
            # --- CRITICAL CHANGE END ---

            last_role = full_hist[-1].get("role") if full_hist else "N/A"
            LOG.info(
                f"[CTX-REFRESH] Fresh DB Fetch: {len(full_hist)} msgs | Last Role: {last_role}"
            )

            self.message_cache.set_history_sync(thread_id, full_hist)
            msgs = full_hist
        else:
            msgs = self.message_cache.get_history_sync(thread_id)
            LOG.debug(f"[CTX-CACHE] Redis Hit for {thread_id}: {len(msgs)} msgs found.")

        # Filter and prepend
        msgs = [m for m in msgs if m.get("role") != "system"]
        full_context = [system_msg] + msgs

        normalized = self._normalize_roles(full_context)

        # Logging the context is great for debugging Turn 2
        LOG.info(f"=== 🚀 OUTBOUND CONTEXT (Size: {len(normalized)}) ===")

        if trunk:
            return self.conversation_truncator.truncate(normalized)

        return normalized

    # -----------------------------------------------------
    # REMAINING SYNC UTILITIES
    # -----------------------------------------------------
    def replace_system_message(
        self, context_window: list[dict], new_system_message: str | None = None
    ) -> list[dict]:
        filtered = [msg for msg in context_window if msg["role"] != "system"]
        if new_system_message is not None:
            filtered.insert(0, {"role": "system", "content": new_system_message})
        return filtered

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
