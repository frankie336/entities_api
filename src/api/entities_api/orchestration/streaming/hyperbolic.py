import json
from collections import defaultdict


class HyperbolicDeltaNormalizer:
    # Standard XML tags
    FC_START, FC_END = "<fc>", "</fc>"
    TH_START, TH_END = "<think>", "</think>"

    # GPT-OSS / Hermes Channel tags
    CH_ANALYSIS = "<|channel|>analysis"
    CH_COMMENTARY = "<|channel|>commentary"
    CH_FINAL = "<|channel|>final"
    MSG_TAG = "<|message|>"
    CALL_TAG = "<|call|>"

    @classmethod
    def iter_deltas(cls, raw_stream, run_id, debug_mode=False):
        """
        Stream processor with Real-Time fix applied.
        """
        buffer = ""
        state = "content"

        # State for Native Tool Accumulation
        pending_tool_calls = defaultdict(
            lambda: {"index": 0, "function": {"name": None, "arguments": ""}}
        )

        for token in raw_stream:
            seg = ""
            choices = []

            # Helper to normalize access between Dict (AsyncClient) and Object (OpenAI SDK)
            is_dict = isinstance(token, dict)

            # --- 1. Normalize Access to Delta ---
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

            # =========================================================
            # FAST PATH 1: DEBUG MODE
            # =========================================================
            if debug_mode:
                seg = (
                    delta.get("content", "")
                    if is_dict
                    else getattr(delta, "content", "")
                ) or ""
                if seg:
                    yield {"type": "content", "content": seg, "run_id": run_id}
                r_content = (
                    delta.get("reasoning_content")
                    if is_dict
                    else getattr(delta, "reasoning_content", None)
                )
                if r_content:
                    yield {"type": "reasoning", "content": r_content, "run_id": run_id}
                continue

            # =========================================================
            # FAST PATH 2: Native Reasoning
            # =========================================================
            r_content = (
                delta.get("reasoning_content")
                if is_dict
                else getattr(delta, "reasoning_content", None)
            )

            if r_content:
                yield {
                    "type": "reasoning",
                    "content": r_content,
                    "run_id": run_id,
                }

            # --- 3. Handle Native Tool Calls ---
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

                    if fn_name:
                        tool_data["function"]["name"] = fn_name
                        yield {
                            "type": "tool_name",
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

            # --- 4. Handle Standard Content ---
            seg = (
                delta.get("content", "") if is_dict else getattr(delta, "content", "")
            ) or ""

            # --- 5. Handle Tool Completion Trigger ---
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

            # =========================================================
            # ⚡ LAG FIX: THE FAST PATH ⚡
            # =========================================================
            # If no tags are initiating, flush immediately.
            if state == "content" and "<" not in buffer:
                yield {"type": "content", "content": buffer, "run_id": run_id}
                buffer = ""
                continue

            # --- 6. Complex State Machine ---
            while buffer:
                yielded_something = False

                if state == "content":
                    # Look for any complete tags
                    potential_tags = [
                        (cls.CH_ANALYSIS, "channel_reasoning"),
                        (cls.CH_COMMENTARY, "channel_tool_meta"),
                        (cls.CH_FINAL, None),
                        (cls.MSG_TAG, None),
                        (cls.FC_START, "fc"),
                        (cls.TH_START, "think"),
                    ]

                    # 1. Check for complete tags match
                    tag_found = False
                    for tag, new_state in potential_tags:
                        if tag in buffer:
                            pre, post = buffer.split(tag, 1)
                            if pre:
                                yield {
                                    "type": "content",
                                    "content": pre,
                                    "run_id": run_id,
                                }
                            if new_state:
                                state = new_state
                            buffer = post
                            yielded_something = True
                            tag_found = True
                            break
                    if tag_found:
                        continue

                    # 2. Optimization: If buffer doesn't contain '<', yield all
                    if "<" not in buffer:
                        yield {"type": "content", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    # 3. Partial tag check
                    # We only hold back if the buffer *ends* with a partial tag prefix
                    # Find the last '<'
                    last_bracket = buffer.rfind("<")

                    if last_bracket == -1:
                        # Should be covered by step 2, but safety net
                        yield {"type": "content", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    # Yield everything before the bracket
                    if last_bracket > 0:
                        yield {
                            "type": "content",
                            "content": buffer[:last_bracket],
                            "run_id": run_id,
                        }
                        buffer = buffer[last_bracket:]
                        # Now buffer starts with '<'

                    # Check if this '<...' is a valid prefix of any known tag
                    all_tags = [
                        cls.CH_ANALYSIS,
                        cls.CH_COMMENTARY,
                        cls.CH_FINAL,
                        cls.MSG_TAG,
                        cls.FC_START,
                        cls.TH_START,
                    ]

                    is_prefix = False
                    for tag in all_tags:
                        if tag.startswith(buffer):
                            is_prefix = True
                            break

                    if is_prefix:
                        # It's a partial tag, wait for more data
                        break
                    else:
                        # It looked like a tag but isn't (e.g. "< 5"). Yield the '<' and continue
                        yield {
                            "type": "content",
                            "content": buffer[0],
                            "run_id": run_id,
                        }
                        buffer = buffer[1:]
                        yielded_something = True

                elif state == "channel_reasoning":
                    # 1. Check for exit tags
                    if cls.CH_FINAL in buffer:
                        pre, post = buffer.split(cls.CH_FINAL, 1)
                        clean = pre.replace(cls.MSG_TAG, "")
                        if clean:
                            yield {
                                "type": "reasoning",
                                "content": clean,
                                "run_id": run_id,
                            }
                        buffer = post
                        state = "content"
                        yielded_something = True
                        continue

                    if cls.CH_COMMENTARY in buffer:
                        pre, post = buffer.split(cls.CH_COMMENTARY, 1)
                        clean = pre.replace(cls.MSG_TAG, "")
                        if clean:
                            yield {
                                "type": "reasoning",
                                "content": clean,
                                "run_id": run_id,
                            }
                        buffer = post
                        state = "channel_tool_meta"
                        yielded_something = True
                        continue

                    # 2. Handle Message Tag Stripping
                    if cls.MSG_TAG in buffer:
                        buffer = buffer.replace(cls.MSG_TAG, "")
                        yielded_something = True
                        continue

                    # 3. FAST YIELD LOGIC
                    # If no '<', yield all
                    if "<" not in buffer:
                        yield {"type": "reasoning", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    # If there is a '<', yield up to it
                    idx = buffer.find("<")
                    if idx > 0:
                        yield {
                            "type": "reasoning",
                            "content": buffer[:idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[idx:]

                    # Now buffer starts with '<'. Check if it matches specific exit tags OR Msg tag
                    exit_tags = [cls.CH_FINAL, cls.CH_COMMENTARY, cls.MSG_TAG]

                    is_prefix = False
                    for tag in exit_tags:
                        if tag.startswith(buffer):
                            is_prefix = True
                            break

                    if is_prefix:
                        break  # Wait

                    # Not a tag prefix, yield char
                    yield {"type": "reasoning", "content": buffer[0], "run_id": run_id}
                    buffer = buffer[1:]
                    yielded_something = True

                elif state == "channel_tool_meta":
                    # (Logic kept simple as this is usually short metadata)
                    if cls.MSG_TAG in buffer:
                        _, post = buffer.split(cls.MSG_TAG, 1)
                        state = "channel_tool_payload"
                        buffer = post
                        yielded_something = True
                        continue
                    elif cls.CH_FINAL in buffer:
                        state = "content"
                        buffer = ""
                        yielded_something = True
                        continue
                    else:
                        break  # Wait

                elif state == "channel_tool_payload":
                    exit_tags = [cls.CALL_TAG, cls.CH_FINAL, cls.CH_ANALYSIS]
                    found = next((tag for tag in exit_tags if tag in buffer), None)

                    if found:
                        pre, post = buffer.split(found, 1)
                        if pre:
                            yield {
                                "type": "call_arguments",
                                "content": pre,
                                "run_id": run_id,
                            }
                        buffer = post
                        state = (
                            "channel_reasoning"
                            if found == cls.CH_ANALYSIS
                            else "content"
                        )
                        yielded_something = True
                        continue

                    # Streaming Logic for Payload
                    if "<" not in buffer:
                        yield {
                            "type": "call_arguments",
                            "content": buffer,
                            "run_id": run_id,
                        }
                        buffer = ""
                        break

                    idx = buffer.find("<")
                    if idx > 0:
                        yield {
                            "type": "call_arguments",
                            "content": buffer[:idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[idx:]

                    is_prefix = any(tag.startswith(buffer) for tag in exit_tags)
                    if is_prefix:
                        break

                    yield {
                        "type": "call_arguments",
                        "content": buffer[0],
                        "run_id": run_id,
                    }
                    buffer = buffer[1:]
                    yielded_something = True

                elif state == "fc":
                    if cls.FC_END in buffer:
                        pre, post = buffer.split(cls.FC_END, 1)
                        if pre:
                            yield {
                                "type": "call_arguments",
                                "content": pre,
                                "run_id": run_id,
                            }
                        state = "content"
                        buffer = post
                        yielded_something = True
                        continue

                    # Streaming Logic
                    if "<" not in buffer:
                        yield {
                            "type": "call_arguments",
                            "content": buffer,
                            "run_id": run_id,
                        }
                        buffer = ""
                        break

                    idx = buffer.find("<")
                    if idx > 0:
                        yield {
                            "type": "call_arguments",
                            "content": buffer[:idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[idx:]

                    if cls.FC_END.startswith(buffer):
                        break

                    yield {
                        "type": "call_arguments",
                        "content": buffer[0],
                        "run_id": run_id,
                    }
                    buffer = buffer[1:]
                    yielded_something = True

                elif state == "think":
                    # 1. Check for end tag
                    if cls.TH_END in buffer:
                        pre, post = buffer.split(cls.TH_END, 1)
                        if pre:
                            yield {
                                "type": "reasoning",
                                "content": pre,
                                "run_id": run_id,
                            }
                        state = "content"
                        buffer = post
                        yielded_something = True
                        continue

                    # 2. FAST YIELD: If no '<', strictly content
                    if "<" not in buffer:
                        yield {"type": "reasoning", "content": buffer, "run_id": run_id}
                        buffer = ""
                        break

                    # 3. If '<' exists, yield up to it
                    idx = buffer.find("<")
                    if idx > 0:
                        yield {
                            "type": "reasoning",
                            "content": buffer[:idx],
                            "run_id": run_id,
                        }
                        buffer = buffer[idx:]

                    # 4. Buffer now starts with '<'. Check if it's the specific close tag
                    if cls.TH_END.startswith(buffer):
                        break  # Wait for more tokens to complete the tag

                    # 5. It starts with '<' but NOT the close tag (e.g. "<div>" vs "</think>")
                    yield {"type": "reasoning", "content": buffer[0], "run_id": run_id}
                    buffer = buffer[1:]
                    yielded_something = True

                    if not yielded_something:
                        break

        # Flush remaining buffer
        if buffer:
            if state == "channel_reasoning" or state == "think":
                clean = buffer.replace(cls.MSG_TAG, "")
                if clean:
                    yield {"type": "reasoning", "content": clean, "run_id": run_id}
            elif state == "channel_tool_payload" or state == "fc":
                yield {"type": "call_arguments", "content": buffer, "run_id": run_id}
            elif state == "content":
                yield {"type": "content", "content": buffer, "run_id": run_id}
