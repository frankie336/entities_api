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
            # We explicitly check for reasoning_content to filter it out of normal content
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
                    # Normalize Dict vs Object access for Tool Call
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
            # Only process content if we didn't just process reasoning (unless they come together)
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

            # --- 6. Character-by-character parsing (Legacy / Channels) ---
            # Only proceed if we have content segment
            for char in seg:
                buffer += char

                if state == "content":
                    if cls.CH_ANALYSIS.startswith(buffer):
                        if buffer == cls.CH_ANALYSIS:
                            state = "channel_reasoning"
                            buffer = ""
                        continue
                    elif cls.CH_COMMENTARY.startswith(buffer):
                        if buffer == cls.CH_COMMENTARY:
                            state = "channel_tool_meta"
                            buffer = ""
                        continue
                    elif cls.CH_FINAL.startswith(buffer):
                        if buffer == cls.CH_FINAL:
                            buffer = ""
                        continue
                    elif cls.MSG_TAG.startswith(buffer):
                        if buffer == cls.MSG_TAG:
                            buffer = ""
                        continue
                    elif cls.FC_START.startswith(buffer):
                        if buffer == cls.FC_START:
                            state = "fc"
                            buffer = ""
                        continue
                    elif cls.TH_START.startswith(buffer):
                        if buffer == cls.TH_START:
                            state = "think"
                            buffer = ""
                        continue

                    # Yield normalized content
                    yield {"type": "content", "content": buffer, "run_id": run_id}
                    buffer = ""

                # ... (Existing state machine logic for channel_reasoning/tool_meta/fc/think) ...
                # Copying the rest of your state machine logic unchanged below for completeness
                elif state == "channel_reasoning":
                    if cls.CH_FINAL in buffer or cls.CH_COMMENTARY in buffer:
                        tag = (
                            cls.CH_FINAL
                            if cls.CH_FINAL in buffer
                            else cls.CH_COMMENTARY
                        )
                        pre, post = buffer.split(tag, 1)
                        clean_pre = pre.replace(cls.MSG_TAG, "")
                        if clean_pre:
                            yield {
                                "type": "reasoning",
                                "content": clean_pre,
                                "run_id": run_id,
                            }
                        buffer = post
                        state = (
                            "channel_tool_meta"
                            if tag == cls.CH_COMMENTARY
                            else "content"
                        )
                        if state == "content":
                            buffer = buffer.replace(cls.MSG_TAG, "")
                    elif any(
                        cls.CH_FINAL.startswith(buffer[i:])
                        or cls.CH_COMMENTARY.startswith(buffer[i:])
                        for i in range(len(buffer))
                    ):
                        continue
                    elif any(
                        cls.MSG_TAG.startswith(buffer[i:]) for i in range(len(buffer))
                    ):
                        if buffer == cls.MSG_TAG:
                            buffer = ""
                        continue
                    else:
                        clean_buf = buffer.replace(cls.MSG_TAG, "")
                        if clean_buf:
                            yield {
                                "type": "reasoning",
                                "content": clean_buf,
                                "run_id": run_id,
                            }
                        buffer = ""

                elif state == "channel_tool_meta":
                    if cls.MSG_TAG in buffer:
                        _, post = buffer.split(cls.MSG_TAG, 1)
                        state = "channel_tool_payload"
                        buffer = post
                    elif cls.CH_FINAL in buffer:
                        state = "content"
                        buffer = ""

                elif state == "channel_tool_payload":
                    exit_tags = [cls.CALL_TAG, cls.CH_FINAL, cls.CH_ANALYSIS]
                    found_tag = next((tag for tag in exit_tags if tag in buffer), None)
                    if found_tag:
                        pre, post = buffer.split(found_tag, 1)
                        if pre:
                            yield {
                                "type": "call_arguments",
                                "content": pre,
                                "run_id": run_id,
                            }
                        buffer = post
                        state = (
                            "channel_reasoning"
                            if found_tag == cls.CH_ANALYSIS
                            else "content"
                        )
                    elif any(
                        tag.startswith(buffer[i:])
                        for tag in exit_tags
                        for i in range(len(buffer))
                    ):
                        continue
                    else:
                        yield {
                            "type": "call_arguments",
                            "content": buffer,
                            "run_id": run_id,
                        }
                        buffer = ""

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
                    elif any(
                        cls.FC_END.startswith(buffer[i:]) for i in range(len(buffer))
                    ):
                        continue
                    else:
                        yield {
                            "type": "call_arguments",
                            "content": buffer,
                            "run_id": run_id,
                        }
                        buffer = ""

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
                    elif any(
                        cls.TH_END.startswith(buffer[i:]) for i in range(len(buffer))
                    ):
                        continue
                    else:
                        yield {"type": "reasoning", "content": buffer, "run_id": run_id}
                        buffer = ""
