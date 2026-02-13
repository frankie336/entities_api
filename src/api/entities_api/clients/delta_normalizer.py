from __future__ import annotations

from collections import defaultdict
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from projectdavid_common.utilities.logging_service import LoggingUtility

load_dotenv()
LOG = LoggingUtility()


class DeltaNormalizer:
    # ---------------------------------------------------------
    # [Model: Standard/Anthropic] Standard XML tags
    # ---------------------------------------------------------
    FC_START, FC_END = "<fc>", "</fc>"

    # ---------------------------------------------------------
    # [Model: Qwen] Standard Tool Call Tags
    # ---------------------------------------------------------
    TC_START, TC_END = "<tool_call>", "</tool_call>"

    # ---------------------------------------------------------
    # [Model: Qwen 2.5/Drift] "Lazy" Tool Tags (CRITICAL FIX)
    # ---------------------------------------------------------
    # Qwen sometimes forgets XML and uses these instead:
    TCODE_START, TCODE_END = "<tool_code>", "</tool_code>"
    MD_JSON_START = "```json"
    MD_END = "```"

    # ---------------------------------------------------------
    # [Model: DeepSeek/Generic] Reasoning & Chain of Thought
    # ---------------------------------------------------------
    TH_START, TH_END = "<think>", "</think>"
    DEC_START, DEC_END = "<decision>", "</decision>"
    PLAN_START, PLAN_END = "<plan>", "</plan>"

    # ---------------------------------------------------------
    # [Model: GPT-OSS / Hermes] Channel tags
    # ---------------------------------------------------------
    CH_ANALYSIS = "<|channel|>analysis"
    CH_COMMENTARY = "<|channel|>commentary"
    CH_FINAL = "<|channel|>final"
    MSG_TAG = "<|message|>"
    CALL_TAG = "<|call|>"

    # ---------------------------------------------------------
    # [Model: Kimi K2.5] Moonshot/Kimi Tool Call Tags
    # ---------------------------------------------------------
    KIMI_SEC_START = "<|tool_calls_section_begin|>"
    KIMI_SEC_END = "<|tool_calls_section_end|>"
    KIMI_TC_START = "<|tool_call_begin|>"
    KIMI_ARG_START = "<|tool_call_argument_begin|>"
    KIMI_TC_END = "<|tool_call_end|>"

    @classmethod
    async def async_iter_deltas(
        cls, raw_stream: AsyncGenerator[Any, None], run_id: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Async version of the Delta Normalizer.
        Consumes an async generator (raw_stream) and yields normalized JSON strings.
        """
        buffer = ""
        state = "content"

        # State for Native Tool Accumulation (OpenAI/Azure Style)
        pending_tool_calls = defaultdict(
            lambda: {"index": 0, "function": {"name": "", "arguments": ""}}
        )

        async for token in raw_stream:
            choices = []
            is_dict = isinstance(token, dict)

            if is_dict:
                choices = token.get("choices", [])
                if not choices or not isinstance(choices, list):
                    continue
                delta = choices[0].get("delta", {})
                finish_reason = choices[0].get("finish_reason")
            elif hasattr(token, "choices") and token.choices:
                choices = token.choices
                delta = choices[0].delta
                finish_reason = getattr(choices[0], "finish_reason", None)
            else:
                continue

            # -----------------------------------------------------
            # 1. Handle Native API Fields (Reasoning & Tool Calls)
            # -----------------------------------------------------
            r_content = (
                delta.get("reasoning_content")
                if is_dict
                else getattr(delta, "reasoning_content", None)
            )
            if r_content:
                yield {"type": "reasoning", "content": r_content, "run_id": run_id}

            t_calls = (
                delta.get("tool_calls") if is_dict else getattr(delta, "tool_calls", None)
            )
            if t_calls:
                for tc in t_calls:
                    if is_dict:
                        t_index = tc.get("index", 0)
                        fn = tc.get("function", {})
                        fn_name = fn.get("name")
                        fn_args = fn.get("arguments", "")
                    else:
                        t_index = tc.index
                        fn = tc.function
                        fn_name = getattr(fn, "name", None)
                        fn_args = getattr(fn, "arguments", "")

                    tool_data = pending_tool_calls[t_index]

                    if fn_name:
                        tool_data["function"]["name"] += fn_name
                        yield {
                            "type": "call_arguments",
                            "content": fn_name,
                            "run_id": run_id,
                        }

                    if fn_args:
                        tool_data["function"]["arguments"] += fn_args
                        yield {
                            "type": "call_arguments",
                            "content": fn_args,
                            "run_id": run_id,
                        }

            seg = (
                      (delta.get("content", "") if is_dict else getattr(delta, "content", ""))
                  ) or ""

            if finish_reason == "tool_calls":
                for idx, data in list(pending_tool_calls.items()):
                    name = data["function"]["name"]
                    args = data["function"]["arguments"]
                    if name:
                        yield {
                            "type": "tool_call",
                            "content": {"name": name, "arguments": args},
                            "run_id": run_id,
                        }
                pending_tool_calls.clear()

            if not seg:
                continue

            buffer += seg

            # -----------------------------------------------------
            # 2. State Machine for Text-Based Tags
            # -----------------------------------------------------
            while buffer:
                yielded_something = False

                # --- STATE: CONTENT ---
                if state == "content":
                    # Optimization: Look ahead for '<' or '`'
                    if "<" not in buffer and "`" not in buffer:
                        yield {"type": "content", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    # Find earliest marker
                    lt_idx = buffer.find("<")
                    bt_idx = buffer.find("`")

                    # If both exist, take the smaller positive one; else take the positive one
                    if lt_idx == -1 and bt_idx == -1:
                        # Should be covered by first check, but safety
                        yield {"type": "content", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    if lt_idx != -1 and bt_idx != -1:
                        cutoff = min(lt_idx, bt_idx)
                    else:
                        cutoff = lt_idx if lt_idx != -1 else bt_idx

                    if cutoff > 0:
                        yield {
                            "type": "content",
                            "content": buffer[:cutoff],
                            "run_id": run_id,
                        }
                        buffer = buffer[cutoff:]

                    # Registered Tag Transitions
                    all_tags = [
                        # [GPT-OSS / Hermes]
                        (cls.CH_ANALYSIS, "channel_reasoning"),
                        (cls.CH_COMMENTARY, "channel_tool_meta"),
                        (cls.CH_FINAL, None),
                        (cls.MSG_TAG, None),
                        # [Standard XML]
                        (cls.FC_START, "fc"),
                        # [Qwen - Standard]
                        (cls.TC_START, "tool_call_xml"),
                        # [Qwen - Drift Fixes]
                        (cls.TCODE_START, "tool_code_xml"),
                        (cls.MD_JSON_START, "md_json_block"),
                        # [DeepSeek/Generic]
                        (cls.TH_START, "think"),
                        (cls.DEC_START, "decision"),
                        (cls.PLAN_START, "plan"),
                        # [Kimi K2.5]
                        (cls.KIMI_SEC_START, "kimi_router"),
                    ]

                    match_found = False
                    for tag, new_state in all_tags:
                        if buffer.startswith(tag):
                            if new_state:
                                state = new_state
                            buffer = buffer[len(tag) :]
                            yielded_something = True
                            match_found = True
                            break
                    if match_found:
                        continue

                    # Check partials
                    is_partial = any(tag.startswith(buffer) for tag, _ in all_tags)

                    if is_partial:
                        # Wait for more tokens
                        break
                    else:
                        # False alarm (e.g. "x < y"), yield the char
                        yield {
                            "type": "content",
                            "content": buffer[0],
                            "run_id": run_id,
                        }
                        buffer = buffer[1:]
                        yielded_something = True

                # --- STATE: THINK / PLAN / DECISION (XML BLOCKS) ---
                elif state in ["think", "plan", "decision"]:
                    # Determine end tag and type
                    if state == "think":
                        end_tag, type_name = cls.TH_END, "reasoning"
                    elif state == "plan":
                        end_tag, type_name = cls.PLAN_END, "plan"
                    else:
                        end_tag, type_name = cls.DEC_END, "decision"

                    if "<" not in buffer:
                        yield {"type": type_name, "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    lt_idx = buffer.find("<")
                    if lt_idx > 0:
                        yield {
                            "type": type_name,
                            "content": buffer[:lt_idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[lt_idx:]

                    if buffer.startswith(end_tag):
                        buffer = buffer[len(end_tag) :]
                        state = "content"
                        yielded_something = True
                        continue

                    if end_tag.startswith(buffer):
                        break

                    yield {"type": type_name, "content": buffer[0], "run_id": run_id}
                    buffer = buffer[1:]
                    yielded_something = True

                # --- STATE: TOOL BLOCKS (XML & MARKDOWN) ---
                elif state in ["fc", "tool_call_xml", "tool_code_xml", "md_json_block"]:
                    # Determine End Tag
                    if state == "fc":
                        end_tag = cls.FC_END
                    elif state == "tool_call_xml":
                        end_tag = cls.TC_END
                    elif state == "tool_code_xml":
                        end_tag = cls.TCODE_END
                    else:  # md_json_block
                        end_tag = cls.MD_END

                    # Check for full end tag
                    if buffer.startswith(end_tag):
                        buffer = buffer[len(end_tag) :]
                        state = "content"
                        yielded_something = True
                        continue

                    # Check for partial end tag (wait)
                    if end_tag.startswith(buffer):
                        break

                    # Optimization: Find first char of end_tag
                    first_char = end_tag[0]
                    idx = buffer.find(first_char)

                    if idx == -1:
                        # Yield all
                        yield {
                            "type": "call_arguments",
                            "content": buffer,
                            "run_id": run_id,
                        }
                        buffer = ""
                        break
                    elif idx > 0:
                        # Yield up to start of potential tag
                        yield {
                            "type": "call_arguments",
                            "content": buffer[:idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[idx:]
                        yielded_something = True
                        # Loop continues to hit .startswith check
                    else:
                        # Buffer starts with the char, but wasn't the tag.
                        # Yield char and advance.
                        yield {
                            "type": "call_arguments",
                            "content": buffer[0],
                            "run_id": run_id,
                        }
                        buffer = buffer[1:]
                        yielded_something = True

                # --- STATE: KIMI / MOONSHOT ---
                elif state == "kimi_router":
                    if buffer.startswith(cls.KIMI_SEC_END):
                        buffer = buffer[len(cls.KIMI_SEC_END) :]
                        state = "content"
                        yielded_something = True
                        continue
                    if buffer.startswith(cls.KIMI_ARG_START):
                        buffer = buffer[len(cls.KIMI_ARG_START) :]
                        state = "kimi_args"
                        yielded_something = True
                        continue
                    if buffer.startswith(cls.KIMI_TC_START):
                        buffer = buffer[len(cls.KIMI_TC_START) :]
                        yielded_something = True
                        continue
                    if buffer.startswith(cls.KIMI_TC_END):
                        buffer = buffer[len(cls.KIMI_TC_END) :]
                        yielded_something = True
                        continue

                    router_tags = [
                        cls.KIMI_SEC_END,
                        cls.KIMI_ARG_START,
                        cls.KIMI_TC_START,
                        cls.KIMI_TC_END,
                    ]
                    if any(tag.startswith(buffer) for tag in router_tags):
                        break

                    # Discard router noise
                    buffer = buffer[1:]
                    yielded_something = True

                elif state == "kimi_args":
                    if buffer.startswith(cls.KIMI_TC_END):
                        buffer = buffer[len(cls.KIMI_TC_END) :]
                        state = "kimi_router"
                        yielded_something = True
                        continue
                    if cls.KIMI_TC_END.startswith(buffer):
                        break
                    yield {
                        "type": "call_arguments",
                        "content": buffer[0],
                        "run_id": run_id,
                    }
                    buffer = buffer[1:]
                    yielded_something = True

                # --- STATE: HERMES CHANNELS ---
                elif state == "channel_reasoning":
                    if buffer.startswith(cls.CH_FINAL):
                        buffer = buffer[len(cls.CH_FINAL) :]
                        state = "content"
                        yielded_something = True
                        continue
                    if buffer.startswith(cls.CH_COMMENTARY):
                        buffer = buffer[len(cls.CH_COMMENTARY) :]
                        state = "channel_tool_meta"
                        yielded_something = True
                        continue

                    specials = [cls.CH_FINAL, cls.CH_COMMENTARY]
                    if any(tag.startswith(buffer) for tag in specials):
                        break

                    yield {"type": "reasoning", "content": buffer[0], "run_id": run_id}
                    buffer = buffer[1:]
                    yielded_something = True

                elif state == "channel_tool_meta":
                    if cls.MSG_TAG in buffer:
                        _, post = buffer.split(cls.MSG_TAG, 1)
                        state = "channel_tool_payload"
                        buffer = post
                        yielded_something = True
                    elif cls.CH_FINAL in buffer:
                        state = "content"
                        buffer = ""
                        yielded_something = True
                    else:
                        break

                elif state == "channel_tool_payload":
                    exit_tags = [cls.CALL_TAG, cls.CH_FINAL, cls.CH_ANALYSIS]
                    if any(buffer.startswith(t) for t in exit_tags):
                        matched = next(t for t in exit_tags if buffer.startswith(t))
                        state = (
                            "channel_reasoning"
                            if matched == cls.CH_ANALYSIS
                            else "content"
                        )
                        buffer = buffer[len(matched) :]
                        yielded_something = True
                        continue
                    if any(t.startswith(buffer) for t in exit_tags):
                        break
                    yield {
                        "type": "call_arguments",
                        "content": buffer[0],
                        "run_id": run_id,
                    }
                    buffer = buffer[1:]
                    yielded_something = True

                if not yielded_something:
                    break

        # Flush any remaining native tools
        if pending_tool_calls:
            for idx, data in list(pending_tool_calls.items()):
                name = data["function"]["name"]
                args = data["function"]["arguments"]
                if name:
                    yield {
                        "type": "tool_call",
                        "content": {"name": name, "arguments": args},
                        "run_id": run_id,
                    }
            pending_tool_calls.clear()

        # Flush remaining buffer
        if buffer:
            if state in ["channel_reasoning", "think"]:
                yield {"type": "reasoning", "content": buffer, "run_id": run_id}
            elif state in [
                "channel_tool_payload",
                "fc",
                "tool_call_xml",
                "tool_code_xml",
                "md_json_block",
                "kimi_args",
            ]:
                yield {"type": "call_arguments", "content": buffer, "run_id": run_id}
            elif state == "decision":
                yield {"type": "decision", "content": buffer, "run_id": run_id}
            elif state == "plan":
                yield {"type": "plan", "content": buffer, "run_id": run_id}
            elif state == "content":
                yield {"type": "content", "content": buffer, "run_id": run_id}
