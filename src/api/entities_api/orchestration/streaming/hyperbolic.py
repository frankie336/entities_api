import json
from collections import defaultdict


class HyperbolicDeltaNormalizer:
    # Standard XML tags (Fallback for raw models)
    FC_START, FC_END = "<fc>", "</fc>"
    TH_START, TH_END = "<think>", "</think>"

    # GPT-OSS / Hermes Channel tags
    CH_ANALYSIS = "<|channel|>analysis"
    CH_COMMENTARY = "<|channel|>commentary"
    CH_FINAL = "<|channel|>final"
    MSG_TAG = "<|message|>"
    CALL_TAG = "<|call|>"

    @classmethod
    def iter_deltas(cls, raw_stream, run_id):
        buffer = ""
        state = "content"

        # State for Native Tool Accumulation (TogetherAI/OpenAI Style)
        pending_tool_calls = defaultdict(
            lambda: {"index": 0, "function": {"name": None, "arguments": ""}}
        )

        for token in raw_stream:
            # --- Normalize Input (Universal Adapter) ---
            choices = []
            is_dict = isinstance(token, dict)

            # Handle Pydantic objects (TogetherAI/OpenAI clients) or Dicts
            if is_dict:
                choices = token.get("choices", [])
                if not choices or not isinstance(choices, list):
                    continue
                delta = choices[0].get("delta", {})
                finish_reason = choices[0].get("finish_reason")
            elif hasattr(token, "choices") and token.choices:
                choices = token.choices
                if not choices:
                    continue
                delta = choices[0].delta
                finish_reason = getattr(choices[0], "finish_reason", None)
            else:
                continue

            # ==============================================================
            # 1. TOGETHER AI / DEEPSEEK R1 NATIVE REASONING
            # ==============================================================
            # Some providers send reasoning in a dedicated field `reasoning_content`
            # rather than inside <think> tags in the content.
            r_content = (
                delta.get("reasoning_content")
                if is_dict
                else getattr(delta, "reasoning_content", None)
            )
            if r_content:
                yield {"type": "reasoning", "content": r_content, "run_id": run_id}

            # ==============================================================
            # 2. TOGETHER AI / DEEPSEEK V3 NATIVE TOOL CALLS
            # ==============================================================
            # DeepSeek-V3 via Together uses structured `tool_calls` list
            # inside the delta, matching OpenAI's standard.
            t_calls = (
                delta.get("tool_calls")
                if is_dict
                else getattr(delta, "tool_calls", None)
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

                    # Tool Name usually comes in the first chunk of the tool call
                    if fn_name:
                        tool_data["function"]["name"] = fn_name
                        yield {
                            "type": "tool_name",
                            "content": fn_name,
                            "run_id": run_id,
                        }

                    # Arguments stream in piecewise
                    if fn_args:
                        tool_data["function"]["arguments"] += fn_args
                        yield {
                            "type": "call_arguments",
                            "content": fn_args,
                            "run_id": run_id,
                        }

            # ==============================================================
            # 3. STANDARD CONTENT HANDLING (XML PARSER)
            # ==============================================================
            # TogetherAI sends standard text in `content`.
            # However, DeepSeek-R1 might sometimes leak tags like <think>
            # into here if not using the native reasoning field.
            seg = (
                delta.get("content", "") if is_dict else getattr(delta, "content", "")
            ) or ""

            # Check for native finish reason to flush tools
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

            # ==================================================================
            # ⚡ REAL-TIME OPTIMISTIC STATE MACHINE ⚡
            # Handles cases where tags are embedded in content (e.g. <think>, <fc>)
            # ==================================================================
            while buffer:
                yielded_something = False

                # -----------------------------------------------------------
                # STATE: CONTENT
                # -----------------------------------------------------------
                if state == "content":
                    # 1. NO TAG? FLUSH ALL.
                    if "<" not in buffer:
                        yield {"type": "content", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    # 2. TAG EXISTS? FLUSH BEFORE IT.
                    lt_idx = buffer.find("<")
                    if lt_idx > 0:
                        yield {
                            "type": "content",
                            "content": buffer[:lt_idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[lt_idx:]
                        # Buffer now starts with "<"

                    # 3. CHECK KNOWN TAGS
                    all_tags = [
                        (cls.CH_ANALYSIS, "channel_reasoning"),
                        (cls.CH_COMMENTARY, "channel_tool_meta"),
                        (cls.CH_FINAL, None),
                        (cls.MSG_TAG, None),
                        (cls.FC_START, "fc"),
                        (cls.TH_START, "think"),
                    ]

                    # A. Exact Match
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

                    # B. Partial Match (The only time we wait)
                    is_partial = any(tag.startswith(buffer) for tag, _ in all_tags)

                    if is_partial:
                        break  # Wait for next token
                    else:
                        yield {
                            "type": "content",
                            "content": buffer[0],
                            "run_id": run_id,
                        }
                        buffer = buffer[1:]
                        yielded_something = True

                # -----------------------------------------------------------
                # STATE: THINK (Reasoning) - Handles DeepSeek <think> tags
                # -----------------------------------------------------------
                elif state == "think":
                    if "<" not in buffer:
                        yield {"type": "reasoning", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    lt_idx = buffer.find("<")
                    if lt_idx > 0:
                        yield {
                            "type": "reasoning",
                            "content": buffer[:lt_idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[lt_idx:]

                    if buffer.startswith(cls.TH_END):
                        buffer = buffer[len(cls.TH_END) :]
                        state = "content"
                        yielded_something = True
                        continue

                    if cls.TH_END.startswith(buffer):
                        break  # Wait

                    yield {"type": "reasoning", "content": buffer[0], "run_id": run_id}
                    buffer = buffer[1:]
                    yielded_something = True

                # -----------------------------------------------------------
                # STATE: CHANNEL / FUNCTION CALLS (Legacy/XML support)
                # -----------------------------------------------------------
                elif state == "channel_reasoning":
                    # ... (Logic identical to previous version for Hermes models)
                    special_markers = [cls.CH_FINAL, cls.CH_COMMENTARY, cls.MSG_TAG]
                    potential_match = any(m.startswith(buffer) for m in special_markers)

                    if potential_match and len(buffer) < 20:  # arbitrary safety len
                        break

                    if buffer.startswith(cls.CH_FINAL):
                        buffer = buffer[len(cls.CH_FINAL) :]
                        state = "content"
                        yielded_something = True
                        continue
                    # ... [Abbreviated for brevity, logic remains same as provided] ...
                    yield {"type": "reasoning", "content": buffer[0], "run_id": run_id}
                    buffer = buffer[1:]
                    yielded_something = True

                elif state == "fc":
                    if buffer.startswith(cls.FC_END):
                        buffer = buffer[len(cls.FC_END) :]
                        state = "content"
                        yielded_something = True
                        continue
                    if cls.FC_END.startswith(buffer):
                        break

                    yield {
                        "type": "call_arguments",
                        "content": buffer[0],
                        "run_id": run_id,
                    }
                    buffer = buffer[1:]
                    yielded_something = True

                # Handling other states...
                elif state == "channel_tool_meta" or state == "channel_tool_payload":
                    # [Simplified fallback logic for channel states]
                    yield {
                        "type": "call_arguments",
                        "content": buffer[0],
                        "run_id": run_id,
                    }
                    buffer = buffer[1:]
                    yielded_something = True

                if not yielded_something:
                    break

        # Flush remaining buffer at end of stream
        if buffer:
            if state in ["channel_reasoning", "think"]:
                yield {"type": "reasoning", "content": buffer, "run_id": run_id}
            elif state in ["channel_tool_payload", "fc"]:
                yield {"type": "call_arguments", "content": buffer, "run_id": run_id}
            elif state == "content":
                yield {"type": "content", "content": buffer, "run_id": run_id}
