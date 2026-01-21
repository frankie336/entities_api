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
    def iter_deltas(cls, raw_stream, run_id):
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

            # --- 2. Handle Native Reasoning (DeepSeek/Hyperbolic Specific) ---
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

            # --- 6. Add entire segment to buffer, then process ---
            buffer += seg

            # Process buffer and yield chunks immediately
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
                            break

                    if yielded_something:
                        continue

                    # Check if buffer might be starting a tag
                    all_tags = [
                        cls.CH_ANALYSIS,
                        cls.CH_COMMENTARY,
                        cls.CH_FINAL,
                        cls.MSG_TAG,
                        cls.FC_START,
                        cls.TH_START,
                    ]
                    max_tag_len = max(len(t) for t in all_tags)

                    if len(buffer) <= max_tag_len:
                        is_potential = any(tag.startswith(buffer) for tag in all_tags)
                        if is_potential:
                            break  # Wait for more data

                    # Yield safe portion
                    if len(buffer) > max_tag_len:
                        safe = buffer[:-max_tag_len]
                        yield {"type": "content", "content": safe, "run_id": run_id}
                        buffer = buffer[-max_tag_len:]
                        yielded_something = True

                    if not yielded_something:
                        break

                elif state == "channel_reasoning":
                    # Look for exit tags
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

                    # Strip message tags
                    if cls.MSG_TAG in buffer:
                        before_msg = buffer
                        buffer = buffer.replace(cls.MSG_TAG, "")
                        if buffer != before_msg:
                            yielded_something = True
                            continue

                    # Check if building exit tag
                    exit_tags = [cls.CH_FINAL, cls.CH_COMMENTARY]
                    max_exit = max(len(t) for t in exit_tags)

                    if len(buffer) <= max_exit:
                        is_potential = any(tag.startswith(buffer) for tag in exit_tags)
                        if is_potential:
                            break  # Wait for more data

                    # Yield safe reasoning content
                    if len(buffer) > max_exit:
                        safe = buffer[:-max_exit]
                        yield {"type": "reasoning", "content": safe, "run_id": run_id}
                        buffer = buffer[-max_exit:]
                        yielded_something = True

                    if not yielded_something:
                        break

                elif state == "channel_tool_meta":
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
                        break  # Wait for more data

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

                    max_exit = max(len(t) for t in exit_tags)
                    if len(buffer) <= max_exit:
                        is_potential = any(tag.startswith(buffer) for tag in exit_tags)
                        if is_potential:
                            break

                    if len(buffer) > max_exit:
                        safe = buffer[:-max_exit]
                        yield {
                            "type": "call_arguments",
                            "content": safe,
                            "run_id": run_id,
                        }
                        buffer = buffer[-max_exit:]
                        yielded_something = True

                    if not yielded_something:
                        break

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

                    tag_len = len(cls.FC_END)
                    if len(buffer) <= tag_len:
                        if cls.FC_END.startswith(buffer):
                            break

                    if len(buffer) > tag_len:
                        safe = buffer[:-tag_len]
                        yield {
                            "type": "call_arguments",
                            "content": safe,
                            "run_id": run_id,
                        }
                        buffer = buffer[-tag_len:]
                        yielded_something = True

                    if not yielded_something:
                        break

                elif state == "think":
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

                    tag_len = len(cls.TH_END)
                    if len(buffer) <= tag_len:
                        if cls.TH_END.startswith(buffer):
                            break

                    if len(buffer) > tag_len:
                        safe = buffer[:-tag_len]
                        yield {"type": "reasoning", "content": safe, "run_id": run_id}
                        buffer = buffer[-tag_len:]
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
